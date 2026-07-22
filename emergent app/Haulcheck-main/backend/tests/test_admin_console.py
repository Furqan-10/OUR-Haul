"""Platform administration: access control, tenant management, audit trail.

The console reaches across every organisation, so the tests that matter most
are the negative ones: that an ordinary user cannot reach it, cannot grant
themselves the role, and that an impersonated session cannot write.

Granting the role requires database access by design, so the fixture writes
`platform_role` directly -- exactly as `scripts/grant_admin.py` does. That the
role is *unreachable through the API* is itself asserted below.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

from conftest import _resolve_base_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = f"{_resolve_base_url()}/api"
PASSWORD = "Platform-Ops-2026!"
TIMEOUT = 20


def _db():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _register(label: str) -> dict:
    email = f"test_admin_{label.lower()}_{uuid.uuid4().hex[:8]}@haulcheck-test.co.uk"
    r = requests.post(f"{API}/auth/register",
                      json={"email": email, "password": PASSWORD, "name": f"TEST {label}"},
                      timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    return {"email": email, "token": body["token"], "user": body["user"],
            "headers": {"Authorization": f"Bearer {body['token']}"}}


@pytest.fixture(scope="module")
def normal_user():
    return _register("normal")


@pytest.fixture(scope="module")
def admin():
    """An account promoted the only way the role can be granted: in the database."""
    account = _register("super")
    _db().users.update_one({"user_id": account["user"]["user_id"]},
                           {"$set": {"platform_role": "platform_admin"}})
    # The role is resolved at authentication, so a fresh login is required.
    r = requests.post(f"{API}/auth/login",
                      json={"email": account["email"], "password": PASSWORD}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    account["token"] = r.json()["token"]
    account["headers"] = {"Authorization": f"Bearer {account['token']}"}
    return account


class TestAccessControl:
    ADMIN_PATHS = [
        "organisations", "users", "metrics", "audit-log",
    ]

    @pytest.mark.parametrize("path", ADMIN_PATHS)
    def test_ordinary_user_cannot_reach_admin_api(self, normal_user, path):
        r = requests.get(f"{API}/admin/{path}", headers=normal_user["headers"], timeout=TIMEOUT)
        # 404 rather than 403: the admin surface does not confirm it exists.
        assert r.status_code == 404, f"/admin/{path} returned {r.status_code}"

    @pytest.mark.parametrize("path", ADMIN_PATHS)
    def test_anonymous_cannot_reach_admin_api(self, path):
        r = requests.get(f"{API}/admin/{path}", timeout=TIMEOUT)
        assert r.status_code in (401, 404)

    def test_admin_can_reach_admin_api(self, admin):
        r = requests.get(f"{API}/admin/metrics", headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_platform_role_is_not_grantable_through_registration(self):
        """Self-registration must not be able to ask for the role."""
        email = f"test_esc_{uuid.uuid4().hex[:8]}@haulcheck-test.co.uk"
        r = requests.post(f"{API}/auth/register",
                          json={"email": email, "password": PASSWORD, "name": "Escalate",
                                "platform_role": "platform_admin", "role": "platform_admin"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['token']}"}
        me = requests.get(f"{API}/auth/me", headers=headers, timeout=TIMEOUT).json()
        assert me["platform_role"] == "user", "registration granted platform administration"
        assert requests.get(f"{API}/admin/metrics", headers=headers,
                            timeout=TIMEOUT).status_code == 404


class TestTenantManagement:
    def test_lists_every_organisation(self, admin, normal_user):
        r = requests.get(f"{API}/admin/organisations?limit=200",
                         headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 2
        ids = [o["org_id"] for o in body["organisations"]]
        # An admin sees other tenants -- the whole point of the console.
        assert normal_user["user"]["org_id"] in ids or body["total"] > len(ids)

    def test_organisation_detail_includes_record_counts(self, admin, normal_user):
        r = requests.get(f"{API}/admin/organisations/{normal_user['user']['org_id']}",
                         headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["org_id"] == normal_user["user"]["org_id"]
        assert "record_counts" in body and "members" in body

    def test_suspending_an_organisation_locks_out_its_members(self, admin):
        """Suspension must take effect immediately, for every member."""
        victim = _register("victim")
        org_id = victim["user"]["org_id"]
        assert requests.get(f"{API}/auth/me", headers=victim["headers"],
                            timeout=TIMEOUT).status_code == 200

        r = requests.post(f"{API}/admin/organisations/{org_id}/suspend",
                          headers=admin["headers"], json={"reason": "non-payment"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        assert requests.get(f"{API}/auth/me", headers=victim["headers"],
                            timeout=TIMEOUT).status_code == 401
        login = requests.post(f"{API}/auth/login",
                              json={"email": victim["email"], "password": PASSWORD},
                              timeout=TIMEOUT)
        assert login.status_code == 403

        # ...and reactivation restores access.
        assert requests.post(f"{API}/admin/organisations/{org_id}/reactivate",
                             headers=admin["headers"], timeout=TIMEOUT).status_code == 200
        assert requests.post(f"{API}/auth/login",
                             json={"email": victim["email"], "password": PASSWORD},
                             timeout=TIMEOUT).status_code == 200

    def test_delete_requires_the_exact_organisation_name(self, admin):
        victim = _register("deleteme")
        org_id = victim["user"]["org_id"]
        r = requests.delete(f"{API}/admin/organisations/{org_id}?confirm_name=wrong-name",
                            headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 400, "a mistyped confirmation must not delete a tenant"
        assert requests.get(f"{API}/admin/organisations/{org_id}",
                            headers=admin["headers"], timeout=TIMEOUT).status_code == 200


class TestUserManagement:
    def test_suspending_a_user_revokes_their_live_token(self, admin):
        victim = _register("suspendme")
        assert requests.get(f"{API}/auth/me", headers=victim["headers"],
                            timeout=TIMEOUT).status_code == 200
        r = requests.post(f"{API}/admin/users/{victim['user']['user_id']}/suspend",
                          headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert requests.get(f"{API}/auth/me", headers=victim["headers"],
                            timeout=TIMEOUT).status_code == 401

    def test_revoke_sessions_signs_out_without_disabling(self, admin):
        victim = _register("revokeme")
        r = requests.post(f"{API}/admin/users/{victim['user']['user_id']}/revoke-sessions",
                          headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        # Old token dead...
        assert requests.get(f"{API}/auth/me", headers=victim["headers"],
                            timeout=TIMEOUT).status_code == 401
        # ...but the account still works.
        assert requests.post(f"{API}/auth/login",
                             json={"email": victim["email"], "password": PASSWORD},
                             timeout=TIMEOUT).status_code == 200

    def test_admin_cannot_suspend_themselves(self, admin):
        r = requests.post(f"{API}/admin/users/{admin['user']['user_id']}/suspend",
                          headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 400


class TestImpersonation:
    def test_impersonated_session_can_read_but_not_write(self, admin):
        target = _register("impersonated")
        r = requests.post(f"{API}/admin/impersonate/{target['user']['user_id']}",
                          headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["read_only"] is True
        imp = {"Authorization": f"Bearer {body['token']}"}

        me = requests.get(f"{API}/auth/me", headers=imp, timeout=TIMEOUT)
        assert me.status_code == 200
        assert me.json()["impersonated_by"] == admin["user"]["user_id"]
        assert requests.get(f"{API}/vehicles", headers=imp, timeout=TIMEOUT).status_code == 200

        # Writing as the customer would put changes in their record that they
        # never made, so it is refused.
        w = requests.post(f"{API}/vehicles", headers=imp,
                          json={"registration": "IMP001", "type": "HGV (Rigid)"}, timeout=TIMEOUT)
        assert w.status_code == 403, f"impersonated write was allowed: {w.status_code}"

    def test_impersonated_session_cannot_reach_the_admin_api(self, admin):
        """No escalation loop: a support session is not an admin session."""
        target = _register("imp2")
        token = requests.post(f"{API}/admin/impersonate/{target['user']['user_id']}",
                              headers=admin["headers"], timeout=TIMEOUT).json()["token"]
        r = requests.get(f"{API}/admin/organisations",
                         headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        assert r.status_code in (403, 404)


class TestAuditLog:
    def test_admin_actions_are_recorded(self, admin):
        victim = _register("audited")
        requests.post(f"{API}/admin/users/{victim['user']['user_id']}/suspend",
                      headers=admin["headers"], timeout=TIMEOUT)
        r = requests.get(f"{API}/admin/audit-log?action=admin.user.suspend&limit=50",
                         headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert any(e.get("target_user_id") == victim["user"]["user_id"] for e in entries), \
            "suspending a user was not written to the audit log"

    def test_impersonation_is_recorded(self, admin):
        target = _register("audit_imp")
        requests.post(f"{API}/admin/impersonate/{target['user']['user_id']}",
                      headers=admin["headers"], timeout=TIMEOUT)
        r = requests.get(f"{API}/admin/audit-log?action=admin.impersonate.start&limit=50",
                         headers=admin["headers"], timeout=TIMEOUT)
        assert any(e.get("target_user_id") == target["user"]["user_id"]
                   for e in r.json()["entries"]), "impersonation was not audited"

    def test_audit_entries_record_the_actor(self, admin):
        r = requests.get(f"{API}/admin/audit-log?limit=5", headers=admin["headers"],
                         timeout=TIMEOUT)
        entries = r.json()["entries"]
        assert entries, "audit log is empty"
        assert all(e.get("actor_email") for e in entries)

    def test_no_endpoint_mutates_the_audit_log(self, admin):
        """The log is append-only: nothing exposes a delete or edit."""
        eid = "any"
        for method, url in [
            ("delete", f"{API}/admin/audit-log/{eid}"),
            ("put", f"{API}/admin/audit-log/{eid}"),
            ("post", f"{API}/admin/audit-log/{eid}/delete"),
        ]:
            r = getattr(requests, method)(url, headers=admin["headers"], timeout=TIMEOUT)
            assert r.status_code in (404, 405), \
                f"{method.upper()} {url} exists -- the audit log must be append-only"


class TestMetrics:
    def test_metrics_report_platform_totals(self, admin):
        r = requests.get(f"{API}/admin/metrics?days=30", headers=admin["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert body["organisations"]["total"] >= 1
        assert body["users"]["total"] >= 1
        assert "signups_by_day" in body and "records" in body
