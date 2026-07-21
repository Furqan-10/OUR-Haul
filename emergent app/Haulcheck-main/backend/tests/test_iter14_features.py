"""
Iteration 14 backend tests:
1) Walkaround defect rectification flow (PUT /api/walkarounds/{id}/rectify).
2) Multi-tenancy / data isolation — a newly registered user must NOT see the
   seeded manager account's data, nor should the manager see the new user's data.
"""
import os
import uuid
import requests
import pytest
from pathlib import Path


# ---------- Config ----------
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
API = f"{BASE_URL}/api"

SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Test1234!"


# ---------- Helpers ----------
def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login_or_register(email, password, name="Test User"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code == 200:
        return r.json()["token"], r.json()["user"]
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name}, timeout=20)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def manager_token():
    tok, _ = _login_or_register(SEED_EMAIL, SEED_PASSWORD, "Fleet Manager")
    return tok


@pytest.fixture(scope="module")
def new_user():
    """Register a brand-new isolated user for the isolation test."""
    email = f"isolation_test+{uuid.uuid4().hex[:10]}@haulcheck.co.uk"
    tok, user = _login_or_register(email, "Test1234!", "Isolation Tester")
    yield {"token": tok, "email": email, "user_id": user["user_id"]}


# ==============================================================
# 1. Walkaround rectify flow
# ==============================================================
class TestWalkaroundRectify:
    def _create_defect_walkaround(self, tok, reg="TEST_WLK1", defects="Brake light out"):
        payload = {
            "vehicle_reg": reg,
            "driver_name": "TEST Driver",
            "check_date": "2026-01-08",
            "result": "defects_found",
            "mileage": "100000",
            "defects_noted": defects,
            "attachments": [],
        }
        r = requests.post(f"{API}/walkarounds", json=payload, headers=_headers(tok), timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def test_rectify_sets_flags_and_persists(self, manager_token):
        wk = self._create_defect_walkaround(manager_token)
        wid = wk["id"]
        assert wk.get("rectified") is False

        r = requests.put(
            f"{API}/walkarounds/{wid}/rectify",
            json={"rectified_date": "2026-01-09", "rectified_notes": "TEST Replaced bulb"},
            headers=_headers(manager_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # GET verifies persistence
        r = requests.get(f"{API}/walkarounds", headers=_headers(manager_token), timeout=15)
        assert r.status_code == 200
        rec = next((x for x in r.json() if x["id"] == wid), None)
        assert rec is not None, "walkaround disappeared"
        assert rec["rectified"] is True
        assert rec["rectified_date"] == "2026-01-09"
        assert rec["rectified_notes"] == "TEST Replaced bulb"

        # cleanup
        requests.delete(f"{API}/walkarounds/{wid}", headers=_headers(manager_token), timeout=15)

    def test_rectify_defaults_date_when_missing(self, manager_token):
        wk = self._create_defect_walkaround(manager_token, reg="TEST_WLK2")
        wid = wk["id"]
        r = requests.put(
            f"{API}/walkarounds/{wid}/rectify",
            json={"rectified_date": None, "rectified_notes": ""},
            headers=_headers(manager_token), timeout=15,
        )
        assert r.status_code == 200

        r = requests.get(f"{API}/walkarounds", headers=_headers(manager_token), timeout=15)
        rec = next(x for x in r.json() if x["id"] == wid)
        assert rec["rectified"] is True
        # Should have defaulted to today's ISO date (YYYY-MM-DD)
        assert rec["rectified_date"] and len(rec["rectified_date"]) == 10

        requests.delete(f"{API}/walkarounds/{wid}", headers=_headers(manager_token), timeout=15)

    def test_rectify_404_when_not_found(self, manager_token):
        r = requests.put(
            f"{API}/walkarounds/does-not-exist-{uuid.uuid4().hex[:8]}/rectify",
            json={"rectified_date": "2026-01-10", "rectified_notes": ""},
            headers=_headers(manager_token), timeout=15,
        )
        assert r.status_code == 404

    def test_rectify_requires_auth(self, manager_token):
        wk = self._create_defect_walkaround(manager_token, reg="TEST_WLK3")
        wid = wk["id"]
        try:
            r = requests.put(
                f"{API}/walkarounds/{wid}/rectify",
                json={"rectified_date": "2026-01-10", "rectified_notes": ""},
                headers={"Content-Type": "application/json"}, timeout=15,
            )
            assert r.status_code in (401, 403)
        finally:
            requests.delete(f"{API}/walkarounds/{wid}", headers=_headers(manager_token), timeout=15)


# ==============================================================
# 2. Multi-tenancy / data isolation
# ==============================================================
# Endpoints that list per-user resources
LIST_ENDPOINTS = [
    "/vehicles", "/trailers", "/drivers",
    "/documents", "/insurance", "/training",
    "/defects", "/pmi", "/pmi/records", "/wheel-audits",
    "/service-records", "/walkarounds", "/test-history",
    "/fuel", "/tacho", "/links",
]


class TestDataIsolation:
    def test_new_user_sees_empty_lists(self, new_user):
        """Every list endpoint should return [] for a freshly-registered user."""
        tok = new_user["token"]
        failures = []
        for ep in LIST_ENDPOINTS:
            r = requests.get(f"{API}{ep}", headers=_headers(tok), timeout=20)
            if r.status_code != 200:
                failures.append(f"{ep}: HTTP {r.status_code}")
                continue
            data = r.json()
            if not isinstance(data, list):
                failures.append(f"{ep}: expected list, got {type(data).__name__}")
                continue
            if len(data) != 0:
                failures.append(f"{ep}: expected 0, got {len(data)} items")
        assert not failures, "Non-empty lists for new user: " + "; ".join(failures)

    def test_new_user_calendar_empty(self, new_user):
        """Calendar for new user should have no user-generated events."""
        tok = new_user["token"]
        r = requests.get(f"{API}/calendar", headers=_headers(tok), timeout=20)
        assert r.status_code == 200
        events = r.json()
        assert isinstance(events, list)
        # A fresh account has no vehicles/drivers/pmi/etc. so no expiry-derived events either
        assert len(events) == 0, f"Expected empty calendar, got {len(events)}: {events[:3]}"

    def test_new_user_dashboard_zero_counts(self, new_user):
        tok = new_user["token"]
        r = requests.get(f"{API}/dashboard", headers=_headers(tok), timeout=20)
        assert r.status_code == 200
        data = r.json()
        # Common fields - all counts should be 0
        for key in ("vehicles", "drivers", "trailers"):
            if key in data:
                v = data[key]
                # Might be int or dict {total, ...}
                if isinstance(v, dict):
                    assert v.get("total", 0) == 0, f"dashboard.{key}.total != 0: {v}"
                else:
                    assert v == 0, f"dashboard.{key} != 0: {v}"

    def test_isolation_new_user_data_not_visible_to_manager(self, manager_token, new_user):
        """New user adds a vehicle; manager must NOT see it."""
        tok_new = new_user["token"]

        # Baseline manager vehicle registrations
        r = requests.get(f"{API}/vehicles", headers=_headers(manager_token), timeout=20)
        assert r.status_code == 200
        mgr_regs_before = {v["registration"] for v in r.json()}

        # New user creates a vehicle
        unique_reg = f"TEST_ISO_{uuid.uuid4().hex[:6].upper()}"
        payload = {"registration": unique_reg, "vehicle_type": "hgv", "make": "Volvo", "model": "FH"}
        r = requests.post(f"{API}/vehicles", json=payload, headers=_headers(tok_new), timeout=20)
        assert r.status_code == 200, r.text
        new_vehicle_id = r.json()["id"]

        try:
            # New user sees their own vehicle
            r = requests.get(f"{API}/vehicles", headers=_headers(tok_new), timeout=20)
            regs_new = {v["registration"] for v in r.json()}
            assert unique_reg in regs_new
            assert len(regs_new) == 1, f"New user should only see their own vehicle: {regs_new}"

            # Manager still does NOT see the new user's vehicle
            r = requests.get(f"{API}/vehicles", headers=_headers(manager_token), timeout=20)
            mgr_regs_after = {v["registration"] for v in r.json()}
            assert unique_reg not in mgr_regs_after, f"Cross-tenant leak: manager sees {unique_reg}"
            assert mgr_regs_after == mgr_regs_before, "Manager vehicle list changed unexpectedly"

            # Manager can NOT PUT/DELETE the new user's vehicle
            r = requests.delete(f"{API}/vehicles/{new_vehicle_id}", headers=_headers(manager_token), timeout=15)
            # Endpoint returns {ok:true} for any id, but must not actually delete another tenant's row
            r2 = requests.get(f"{API}/vehicles", headers=_headers(tok_new), timeout=20)
            regs_new_after = {v["registration"] for v in r2.json()}
            assert unique_reg in regs_new_after, "Manager DELETE affected another tenant's vehicle (SECURITY)"
        finally:
            requests.delete(f"{API}/vehicles/{new_vehicle_id}", headers=_headers(tok_new), timeout=15)

    def test_manager_still_has_own_data(self, manager_token):
        """Regression: manager account still shows its existing data."""
        r = requests.get(f"{API}/dashboard", headers=_headers(manager_token), timeout=20)
        assert r.status_code == 200
        # Just assert response shape, no strict count (env-dependent)
        data = r.json()
        assert isinstance(data, dict)


# ==============================================================
# 3. Regression smoke: walkaround nil-defect + maintenance list endpoints
# ==============================================================
class TestRegressionSmoke:
    def test_nil_defect_walkaround_has_no_rectify_flag(self, manager_token):
        payload = {
            "vehicle_reg": "TEST_NIL1",
            "driver_name": "TEST Driver",
            "check_date": "2026-01-08",
            "result": "nil_defect",
            "mileage": "50000",
            "defects_noted": "",
            "attachments": [],
        }
        r = requests.post(f"{API}/walkarounds", json=payload, headers=_headers(manager_token), timeout=15)
        assert r.status_code == 200
        wk = r.json()
        assert wk["result"] == "nil_defect"
        assert wk.get("rectified") is False
        # Cleanup
        requests.delete(f"{API}/walkarounds/{wk['id']}", headers=_headers(manager_token), timeout=15)

    def test_maintenance_tab_endpoints_load(self, manager_token):
        for ep in ("/pmi", "/defects", "/service-records", "/wheel-audits", "/walkarounds"):
            r = requests.get(f"{API}{ep}", headers=_headers(manager_token), timeout=20)
            assert r.status_code == 200, f"{ep} returned {r.status_code}"
            assert isinstance(r.json(), list)
