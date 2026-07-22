"""Organisation tenancy: sharing within an org, isolation between orgs.

The behavioural half of the Phase 1 safety net (tests/test_tenancy_guard.py is
the static half). Two things have to hold at once, and they pull in opposite
directions:

  * colleagues in one organisation see the *same* records -- the point of the
    org layer, and impossible before it;
  * nobody sees another organisation's records -- the property that was already
    true per-user and must survive the rewrite.

Fixtures build two real organisations over HTTP, so this exercises the actual
auth path rather than a mocked one.
"""
import uuid

import pytest
import requests

from conftest import _resolve_base_url

API = f"{_resolve_base_url()}/api"
PASSWORD = "Org-Tenant-2026!"
TIMEOUT = 20


def _register(label: str) -> dict:
    """Create an account (and implicitly its organisation).

    The label is lower-cased because registration normalises addresses (an
    intentional fix from iteration 18 -- see memory/PRD.md), so a mixed-case
    label here would not match what the API echoes back.
    """
    email = f"test_{label.lower()}_{uuid.uuid4().hex[:8]}@haulcheck-test.co.uk"
    r = requests.post(f"{API}/auth/register",
                      json={"email": email, "password": PASSWORD, "name": f"TEST {label}"},
                      timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    return {"email": email, "token": body["token"], "user": body["user"],
            "headers": {"Authorization": f"Bearer {body['token']}"}}


def _invite_and_accept(inviter: dict, kind: str, role: str = "manager") -> dict:
    """Invite someone and accept it, returning the new member's session."""
    email = f"test_member_{uuid.uuid4().hex[:8]}@haulcheck-test.co.uk"
    r = requests.post(f"{API}/invitations", headers=inviter["headers"],
                      json={"email": email, "kind": kind, "role": role,
                            "base_url": "http://localhost:3000"}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    token = r.json()["invite_link"].split("token=")[1]
    r = requests.post(f"{API}/auth/accept-invite",
                      json={"token": token, "name": "TEST Member", "password": PASSWORD},
                      timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    return {"email": email, "token": body["token"], "user": body["user"],
            "headers": {"Authorization": f"Bearer {body['token']}"}}


@pytest.fixture(scope="module")
def org_a():
    return _register("orgA_owner")


@pytest.fixture(scope="module")
def org_b():
    return _register("orgB_owner")


@pytest.fixture(scope="module")
def colleague(org_a):
    """A second member of organisation A."""
    return _invite_and_accept(org_a, kind="org", role="manager")


@pytest.fixture(scope="module")
def viewer(org_a):
    """A read-only member of organisation A."""
    return _invite_and_accept(org_a, kind="org", role="viewer")


@pytest.fixture(scope="module")
def vehicle_a(org_a):
    """A vehicle owned by organisation A."""
    reg = f"TEST{uuid.uuid4().hex[:4].upper()}"
    r = requests.post(f"{API}/vehicles", headers=org_a["headers"],
                      json={"registration": reg, "make": "Volvo", "type": "HGV (Rigid)"},
                      timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


class TestOrgContext:
    def test_registration_provisions_an_organisation(self, org_a):
        assert org_a["user"]["org_id"].startswith("org_")
        assert org_a["user"]["org_role"] == "owner"

    def test_two_registrations_get_different_organisations(self, org_a, org_b):
        assert org_a["user"]["org_id"] != org_b["user"]["org_id"]

    def test_auth_me_reports_org_context(self, org_a):
        r = requests.get(f"{API}/auth/me", headers=org_a["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        me = r.json()
        assert me["org_id"] == org_a["user"]["org_id"]
        assert me["org_role"] == "owner"
        # Platform administration must never be reachable by self-registration.
        assert me["platform_role"] == "user"


class TestSharingWithinAnOrganisation:
    """The capability the org layer exists to provide."""

    def test_org_invite_puts_the_member_in_the_same_org(self, org_a, colleague):
        assert colleague["user"]["org_id"] == org_a["user"]["org_id"]
        assert colleague["user"]["org_role"] == "manager"

    def test_colleague_sees_the_shared_fleet(self, colleague, vehicle_a):
        r = requests.get(f"{API}/vehicles", headers=colleague["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        assert vehicle_a["registration"] in [v["registration"] for v in r.json()], \
            "a colleague in the same organisation must see the shared fleet"

    def test_colleague_can_edit_shared_records(self, colleague, vehicle_a):
        r = requests.put(f"{API}/vehicles/{vehicle_a['id']}", headers=colleague["headers"],
                         json={"registration": vehicle_a["registration"], "make": "Scania",
                               "type": "HGV (Rigid)"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_records_created_by_a_colleague_are_visible_to_the_owner(self, org_a, colleague):
        reg = f"COLL{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/vehicles", headers=colleague["headers"],
                          json={"registration": reg, "type": "LGV / Van"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/vehicles", headers=org_a["headers"], timeout=TIMEOUT)
        assert reg in [v["registration"] for v in r.json()]


class TestIsolationBetweenOrganisations:
    """The property that must survive the rewrite."""

    def test_other_org_cannot_list_the_records(self, org_b, vehicle_a):
        r = requests.get(f"{API}/vehicles", headers=org_b["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        assert vehicle_a["registration"] not in [v["registration"] for v in r.json()]

    def test_other_org_cannot_update_by_guessing_an_id(self, org_b, vehicle_a):
        r = requests.put(f"{API}/vehicles/{vehicle_a['id']}", headers=org_b["headers"],
                         json={"registration": "STOLEN", "type": "HGV (Rigid)"}, timeout=TIMEOUT)
        # 404, not 403: confirming an id exists is itself a leak.
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"

    def test_other_org_cannot_delete_by_guessing_an_id(self, org_b, org_a, vehicle_a):
        requests.delete(f"{API}/vehicles/{vehicle_a['id']}", headers=org_b["headers"],
                        timeout=TIMEOUT)
        # Whatever the status, the record must still be there for its owner.
        r = requests.get(f"{API}/vehicles", headers=org_a["headers"], timeout=TIMEOUT)
        assert vehicle_a["registration"] in [v["registration"] for v in r.json()], \
            "a foreign delete must not remove another organisation's record"

    @pytest.mark.parametrize("path", [
        "vehicles", "trailers", "drivers", "defects", "documents", "insurance",
        "tacho", "training", "fuel", "links", "trade-unions", "service-records",
        "wheel-audits", "walkarounds", "pmi", "alerts",
    ])
    def test_every_list_endpoint_is_empty_for_a_fresh_org(self, path):
        """A brand-new organisation starts empty on every collection.

        Catches an endpoint that forgot its org filter: an unscoped query would
        return the whole platform's rows here.
        """
        fresh = _register("fresh")
        r = requests.get(f"{API}/{path}", headers=fresh["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, f"/{path} -> {r.status_code}: {r.text}"
        body = r.json()
        rows = body if isinstance(body, list) else body.get("items", body)
        assert rows == [] or rows == {}, \
            f"/{path} leaked {len(rows)} row(s) into a brand-new organisation"


class TestReferralInvitesStillCreateSeparateAccounts:
    """The pre-existing referral flow must keep working unchanged."""

    def test_referral_member_gets_their_own_org(self, org_a):
        referred = _invite_and_accept(org_a, kind="referral")
        assert referred["user"]["org_id"] != org_a["user"]["org_id"]
        assert referred["user"]["org_role"] == "owner"

    def test_referral_member_sees_none_of_the_inviters_records(self, org_a, vehicle_a):
        referred = _invite_and_accept(org_a, kind="referral")
        r = requests.get(f"{API}/vehicles", headers=referred["headers"], timeout=TIMEOUT)
        assert vehicle_a["registration"] not in [v["registration"] for v in r.json()]


class TestRoles:
    def test_viewer_can_read(self, viewer, vehicle_a):
        r = requests.get(f"{API}/vehicles", headers=viewer["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        assert vehicle_a["registration"] in [v["registration"] for v in r.json()]

    def test_viewer_cannot_write(self, viewer):
        r = requests.post(f"{API}/vehicles", headers=viewer["headers"],
                          json={"registration": "VIEWER1", "type": "HGV (Rigid)"}, timeout=TIMEOUT)
        assert r.status_code == 403, f"a viewer must not be able to create records: {r.text}"

    def test_viewer_cannot_delete(self, viewer, vehicle_a):
        r = requests.delete(f"{API}/vehicles/{vehicle_a['id']}", headers=viewer["headers"],
                            timeout=TIMEOUT)
        assert r.status_code == 403

    def test_manager_cannot_invite_colleagues_into_the_org(self, colleague):
        """Handing out access to the org's data is an owner-only action."""
        r = requests.post(f"{API}/invitations", headers=colleague["headers"],
                          json={"email": f"x_{uuid.uuid4().hex[:6]}@haulcheck-test.co.uk",
                                "kind": "org", "role": "manager"}, timeout=TIMEOUT)
        assert r.status_code == 403, r.text

    def test_owner_cannot_demote_the_last_owner(self, org_a):
        r = requests.put(f"{API}/organisation/members/{org_a['user']['user_id']}/role",
                         headers=org_a["headers"], json={"role": "manager"}, timeout=TIMEOUT)
        assert r.status_code == 400, "an organisation must always keep at least one owner"


class TestOrganisationEndpoint:
    def test_lists_its_own_members(self, org_a, colleague):
        r = requests.get(f"{API}/organisation", headers=org_a["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert body["org_id"] == org_a["user"]["org_id"]
        emails = {m["email"] for m in body["members"]}
        assert org_a["email"] in emails and colleague["email"] in emails

    def test_members_of_another_org_are_not_listed(self, org_a, org_b):
        r = requests.get(f"{API}/organisation", headers=org_a["headers"], timeout=TIMEOUT)
        assert org_b["email"] not in {m["email"] for m in r.json()["members"]}

    def test_region_change_applies_to_the_whole_org(self, org_a, colleague):
        assert requests.put(f"{API}/settings/region", headers=org_a["headers"],
                            json={"region": "IE"}, timeout=TIMEOUT).status_code == 200
        r = requests.get(f"{API}/auth/me", headers=colleague["headers"], timeout=TIMEOUT)
        assert r.json()["region"] == "IE", "region belongs to the organisation, not the user"
        requests.put(f"{API}/settings/region", headers=org_a["headers"],
                     json={"region": "UK"}, timeout=TIMEOUT)
