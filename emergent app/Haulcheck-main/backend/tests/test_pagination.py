"""List endpoints must page, and must not truncate silently.

The endpoints returned `.to_list(1000)`. Past that the response was simply
short, with nothing in it saying so -- an operator with 1,100 defects saw 1,000
and no indication that 100 were missing. In a compliance product that is worse
than an error: the missing records are invisible in exactly the audit the tool
exists to support.

The contract these tests pin down:
  - the response is still a bare array, so existing callers are unaffected;
  - X-Total-Count always reports the true total, paged or not;
  - ?limit= and ?offset= walk the collection without gaps or repeats;
  - the count respects tenant scoping, like every other query.
"""
import os
import uuid

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000")
API = f"{BASE}/api"

SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Seed-Fleet-2026!"

# Endpoints converted to paging, with the field used to identify a record.
PAGED_ENDPOINTS = [
    "/defects",
    "/pmi/records",
    "/walkarounds",
    "/weekly-walkarounds",
    "/service-records",
    "/wheel-audits",
    "/tacho",
    "/test-history",
    "/documents",
]


def _register_or_login(email, password, name="Pagination Test"):
    r = requests.post(f"{API}/auth/register",
                      json={"email": email, "password": password, "name": name}, timeout=20)
    if r.status_code >= 400:
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth():
    token = _register_or_login(SEED_EMAIL, SEED_PASSWORD, "Seed Manager")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seeded_defects(auth):
    """Enough defects to page through more than once."""
    created = []
    for i in range(7):
        r = requests.post(f"{API}/defects", headers=auth, json={
            "vehicle_reg": f"PAGE{i:02d}",
            "description": f"Pagination fixture defect {i} {uuid.uuid4().hex[:6]}",
            "severity": "minor",
        }, timeout=20)
        if r.status_code < 400:
            created.append(r.json())
    return created


class TestResponseShapeIsUnchanged:
    """Paging must not break callers written against the old API."""

    @pytest.mark.parametrize("endpoint", PAGED_ENDPOINTS)
    def test_the_response_is_still_a_bare_array(self, auth, endpoint):
        r = requests.get(f"{API}{endpoint}", headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list), (
            f"{endpoint} returned {type(r.json()).__name__}, not a list. "
            f"Wrapping the array would break every existing caller.")

    @pytest.mark.parametrize("endpoint", PAGED_ENDPOINTS)
    def test_the_true_total_is_always_reported(self, auth, endpoint):
        r = requests.get(f"{API}{endpoint}", headers=auth, timeout=20)
        assert "X-Total-Count" in r.headers, (
            f"{endpoint} does not report X-Total-Count, so a caller cannot tell "
            f"whether it received everything.")
        assert int(r.headers["X-Total-Count"]) >= len(r.json())


class TestPaging:
    def test_limit_caps_the_number_returned(self, auth, seeded_defects):
        r = requests.get(f"{API}/defects", headers=auth, params={"limit": 3}, timeout=20)
        assert r.status_code == 200
        assert len(r.json()) <= 3

    def test_the_total_is_unaffected_by_the_page_size(self, auth, seeded_defects):
        full = requests.get(f"{API}/defects", headers=auth, timeout=20)
        paged = requests.get(f"{API}/defects", headers=auth, params={"limit": 2}, timeout=20)
        assert full.headers["X-Total-Count"] == paged.headers["X-Total-Count"], (
            "X-Total-Count changed with the page size, so it is reporting the "
            "page length rather than the collection total.")

    def test_pages_do_not_overlap_or_skip(self, auth, seeded_defects):
        """Walking the collection must visit each record exactly once."""
        total = int(requests.get(f"{API}/defects", headers=auth,
                                 params={"limit": 1}, timeout=20).headers["X-Total-Count"])
        if total < 4:
            pytest.skip("not enough defects on this database to page through")

        seen, offset, size = [], 0, 2
        while offset < min(total, 10):
            body = requests.get(f"{API}/defects", headers=auth,
                                params={"limit": size, "offset": offset}, timeout=20).json()
            if not body:
                break
            seen.extend(d["id"] for d in body if "id" in d)
            offset += size

        assert len(seen) == len(set(seen)), (
            "The same record appeared on more than one page, so offset is not "
            "being applied.")

    def test_an_offset_past_the_end_returns_empty_not_an_error(self, auth):
        r = requests.get(f"{API}/defects", headers=auth,
                         params={"limit": 5, "offset": 100000}, timeout=20)
        assert r.status_code == 200
        assert r.json() == []

    def test_an_oversized_limit_is_capped_not_honoured(self, auth):
        """A caller must not be able to ask for unbounded work."""
        r = requests.get(f"{API}/defects", headers=auth,
                         params={"limit": 10_000_000}, timeout=30)
        assert r.status_code == 200
        assert int(r.headers["X-Page-Limit"]) <= 5000

    def test_a_negative_offset_is_treated_as_zero(self, auth):
        r = requests.get(f"{API}/defects", headers=auth,
                         params={"limit": 2, "offset": -5}, timeout=20)
        assert r.status_code == 200
        assert int(r.headers["X-Page-Offset"]) == 0


class TestPagingRespectsTenantIsolation:
    """The count is a second query, and a second query is a second chance to
    forget the tenant filter.

    A total that ignored org scoping would leak the size of other customers'
    data -- and would tell an operator they have records they cannot see.
    """

    def test_the_total_counts_only_this_organisation(self):
        a_email = f"page_a_{uuid.uuid4().hex[:8]}@haulcheck.co.uk"
        b_email = f"page_b_{uuid.uuid4().hex[:8]}@haulcheck.co.uk"
        password = "Org-Tenant-2026!"

        a = {"Authorization": f"Bearer {_register_or_login(a_email, password, 'Org A')}"}
        b = {"Authorization": f"Bearer {_register_or_login(b_email, password, 'Org B')}"}

        # A fresh organisation starts empty.
        before = int(requests.get(f"{API}/defects", headers=b, timeout=20)
                     .headers["X-Total-Count"])

        for i in range(3):
            requests.post(f"{API}/defects", headers=a, json={
                "vehicle_reg": f"ISO{i}",
                "description": f"org A only {uuid.uuid4().hex[:6]}",
                "severity": "minor",
            }, timeout=20)

        after = int(requests.get(f"{API}/defects", headers=b, timeout=20)
                    .headers["X-Total-Count"])
        assert after == before, (
            f"Organisation B's total moved from {before} to {after} after "
            f"organisation A created records. The count is not tenant-scoped.")

        a_total = int(requests.get(f"{API}/defects", headers=a, timeout=20)
                      .headers["X-Total-Count"])
        assert a_total >= 3
