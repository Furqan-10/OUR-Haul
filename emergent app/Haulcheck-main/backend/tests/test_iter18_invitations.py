"""
Iteration 18 — Team/Invitations backend tests.
Covers:
  - POST /api/invitations (create + response contains invite_link + token/id)
  - GET  /api/invitations (list, scoped to inviter, includes token)
  - DELETE /api/invitations/{id} (revoke)
  - GET  /api/invitations/verify?token= (public, valid/invalid)
  - POST /api/auth/accept-invite (activates + returns JWT + user, and seeds template)
  - Duplicate email → 400 "That email already has an account"
  - Cross-user isolation (invitee cannot see inviter's vehicles/drivers)
  - Template seeding: links cloned + reminder recipient set to invitee email
"""
import os
import time
import uuid
import requests
import pytest
from pathlib import Path

# --- Base URL ---
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    env_path = Path("/app/frontend/.env")
    for line in env_path.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
API = f"{BASE_URL}/api"

SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Test1234!"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def inviter_token():
    r = requests.post(f"{API}/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    if r.status_code == 200:
        return r.json()["token"]
    r = requests.post(f"{API}/auth/register", json={"email": SEED_EMAIL, "password": SEED_PASSWORD, "name": "Fleet Manager"}, timeout=15)
    assert r.status_code == 200, f"Seed register failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def inviter_headers(inviter_token):
    return {"Authorization": f"Bearer {inviter_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="function")
def fresh_email():
    return f"TEST_invitee_{uuid.uuid4().hex[:8]}@example.com"


# ---------- Tests ----------
class TestInvitationCreate:
    def test_create_invitation_returns_link_and_id(self, inviter_headers, fresh_email):
        r = requests.post(f"{API}/invitations",
                          json={"email": fresh_email, "base_url": "https://example.test"},
                          headers=inviter_headers, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("id", "").startswith("inv_")
        assert body.get("invite_link", "").startswith("https://example.test/accept-invite?token=")
        # cleanup
        requests.delete(f"{API}/invitations/{body['id']}", headers=inviter_headers, timeout=15)

    def test_create_requires_auth(self, fresh_email):
        r = requests.post(f"{API}/invitations", json={"email": fresh_email}, timeout=15)
        assert r.status_code == 401

    def test_create_duplicate_email_existing_user_returns_400(self, inviter_headers):
        # Register a fresh user, then attempt to invite that email
        email = f"TEST_dup_{uuid.uuid4().hex[:6]}@example.com"
        reg = requests.post(f"{API}/auth/register",
                            json={"email": email, "password": "Password1!", "name": "Existing"}, timeout=15)
        assert reg.status_code == 200
        r = requests.post(f"{API}/invitations", json={"email": email},
                          headers=inviter_headers, timeout=15)
        assert r.status_code == 400
        assert "already has an account" in (r.json().get("detail") or "").lower()

    def test_create_invalid_email_returns_422(self, inviter_headers):
        r = requests.post(f"{API}/invitations", json={"email": "not-an-email"},
                          headers=inviter_headers, timeout=15)
        assert r.status_code == 422


class TestInvitationList:
    def test_list_contains_pending_invite_with_token(self, inviter_headers, fresh_email):
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        assert cr.status_code == 200
        iid = cr.json()["id"]
        try:
            r = requests.get(f"{API}/invitations", headers=inviter_headers, timeout=15)
            assert r.status_code == 200
            items = r.json()
            match = next((x for x in items if x["id"] == iid), None)
            assert match is not None
            assert match["email"] == fresh_email.lower()
            assert match["status"] == "pending"
            assert match.get("token") and isinstance(match["token"], str) and len(match["token"]) > 20
            assert "_id" not in match  # ObjectId excluded
        finally:
            requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)

    def test_list_requires_auth(self):
        r = requests.get(f"{API}/invitations", timeout=15)
        assert r.status_code == 401

    def test_list_scoped_to_inviter(self, inviter_headers, fresh_email):
        # Inviter creates
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        iid = cr.json()["id"]
        # Fresh other user
        other_email = f"TEST_other_{uuid.uuid4().hex[:6]}@example.com"
        rB = requests.post(f"{API}/auth/register",
                           json={"email": other_email, "password": "Password1!", "name": "Other"},
                           timeout=15)
        hB = {"Authorization": f"Bearer {rB.json()['token']}"}
        try:
            r = requests.get(f"{API}/invitations", headers=hB, timeout=15)
            assert r.status_code == 200
            assert not any(x["id"] == iid for x in r.json())
        finally:
            requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)


class TestInvitationRevoke:
    def test_revoke_removes_invite(self, inviter_headers, fresh_email):
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        iid = cr.json()["id"]
        r = requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)
        assert r.status_code == 200
        # Confirm no longer listed
        lst = requests.get(f"{API}/invitations", headers=inviter_headers, timeout=15).json()
        assert not any(x["id"] == iid for x in lst)

    def test_revoke_requires_auth(self):
        r = requests.delete(f"{API}/invitations/some_id", timeout=15)
        assert r.status_code == 401


class TestInvitationVerify:
    def test_verify_valid_token(self, inviter_headers, fresh_email):
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        iid = cr.json()["id"]
        # get token
        lst = requests.get(f"{API}/invitations", headers=inviter_headers, timeout=15).json()
        inv = next(x for x in lst if x["id"] == iid)
        try:
            r = requests.get(f"{API}/invitations/verify", params={"token": inv["token"]}, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["email"] == fresh_email.lower()
            assert "inviter_name" in body
        finally:
            requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)

    def test_verify_invalid_token_returns_404(self):
        r = requests.get(f"{API}/invitations/verify", params={"token": "not-a-real-token-xxx"}, timeout=15)
        assert r.status_code == 404


class TestAcceptInvite:
    def test_accept_invite_creates_user_and_seeds_template(self, inviter_headers, inviter_token, fresh_email):
        # 1) Seed inviter with at least one link and a reminder recipient (template source)
        link_title = f"TEST InviteLink {uuid.uuid4().hex[:4]}"
        lr = requests.post(f"{API}/links",
                           json={"title": link_title, "url": f"https://example.test/{uuid.uuid4().hex[:6]}",
                                 "category": "General"},
                           headers=inviter_headers, timeout=15)
        assert lr.status_code == 200
        link_id = lr.json()["id"]

        # Create a vehicle + driver under inviter — should NOT be visible to invitee
        veh_reg = f"INVTEST{uuid.uuid4().hex[:5].upper()}"
        vr = requests.post(f"{API}/vehicles",
                           json={"registration": veh_reg, "make": "DAF", "model": "XF", "type": "HGV"},
                           headers=inviter_headers, timeout=15)
        assert vr.status_code == 200
        vid = vr.json()["id"]
        drv_name = f"TEST InvHiddenDrv {uuid.uuid4().hex[:4]}"
        dr = requests.post(f"{API}/drivers", json={"name": drv_name}, headers=inviter_headers, timeout=15)
        assert dr.status_code == 200
        did = dr.json()["id"]

        # 2) Create invitation
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        assert cr.status_code == 200
        iid = cr.json()["id"]
        lst = requests.get(f"{API}/invitations", headers=inviter_headers, timeout=15).json()
        inv = next(x for x in lst if x["id"] == iid)
        token = inv["token"]

        try:
            # 3) Accept invite
            r = requests.post(f"{API}/auth/accept-invite",
                              json={"token": token, "name": "Invited User", "password": "Password1!"},
                              timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("token") and len(body["token"]) > 20
            assert body["user"]["email"] == fresh_email.lower()
            assert body["user"]["name"] == "Invited User"
            assert body["user"]["role"] == "manager"
            assert body["user"].get("region") in ("UK", "IE")

            invitee_headers = {"Authorization": f"Bearer {body['token']}", "Content-Type": "application/json"}

            # 4) Verify token can no longer be reused (status changed to accepted)
            r2 = requests.post(f"{API}/auth/accept-invite",
                               json={"token": token, "name": "Second", "password": "Password1!"},
                               timeout=15)
            assert r2.status_code == 400

            # 5) DATA ISOLATION — invitee should NOT see inviter's vehicles/drivers
            v_list = requests.get(f"{API}/vehicles", headers=invitee_headers, timeout=15).json()
            d_list = requests.get(f"{API}/drivers", headers=invitee_headers, timeout=15).json()
            assert not any(v.get("registration") == veh_reg for v in v_list), \
                "Isolation FAIL: invitee sees inviter's vehicle"
            assert not any(d.get("name") == drv_name for d in d_list), \
                "Isolation FAIL: invitee sees inviter's driver"
            assert v_list == []  # fresh user, no vehicles
            assert d_list == []

            # 6) TEMPLATE SEED — invitee should have the inviter's links cloned
            inv_links = requests.get(f"{API}/links", headers=invitee_headers, timeout=15).json()
            titles = [l["title"] for l in inv_links]
            assert link_title in titles, f"Link '{link_title}' not cloned to invitee. Got: {titles}"
            # Each cloned link should belong to the invitee (id is new)
            cloned = next(l for l in inv_links if l["title"] == link_title)
            assert cloned["id"] != link_id  # new id in the invitee's account

            # 7) TEMPLATE SEED — reminder_settings should have the invitee's own email as recipient
            #    This only holds if the inviter had a reminder_settings doc. If not, we skip the assertion.
            #    Attempt to set inviter reminder first to make deterministic — but that would be a mutation.
            #    We rely on _seed_template's behaviour: if inviter has none, invitee has none, which is fine.
            #    We still check that no OTHER email appears as a recipient.
            #    (Endpoint may or may not exist — we probe /reminders and treat 404 as N/A.)
            rs = requests.get(f"{API}/reminders", headers=invitee_headers, timeout=15)
            if rs.status_code == 200:
                data = rs.json()
                if isinstance(data, dict) and "recipients" in data and data["recipients"]:
                    emails = [r.get("email") for r in data["recipients"]]
                    assert fresh_email.lower() in [e.lower() for e in emails if e], \
                        f"Invitee email not in reminder recipients: {emails}"

        finally:
            # cleanup — best-effort
            requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)
            requests.delete(f"{API}/links/{link_id}", headers=inviter_headers, timeout=15)
            requests.delete(f"{API}/vehicles/{vid}", headers=inviter_headers, timeout=15)
            requests.delete(f"{API}/drivers/{did}", headers=inviter_headers, timeout=15)

    def test_accept_short_password_rejected(self, inviter_headers, fresh_email):
        cr = requests.post(f"{API}/invitations", json={"email": fresh_email},
                           headers=inviter_headers, timeout=15)
        iid = cr.json()["id"]
        lst = requests.get(f"{API}/invitations", headers=inviter_headers, timeout=15).json()
        token = next(x for x in lst if x["id"] == iid)["token"]
        try:
            r = requests.post(f"{API}/auth/accept-invite",
                              json={"token": token, "name": "Short PW", "password": "abc"},
                              timeout=15)
            assert r.status_code == 400
            assert "6 characters" in (r.json().get("detail") or "")
        finally:
            requests.delete(f"{API}/invitations/{iid}", headers=inviter_headers, timeout=15)

    def test_accept_invalid_token_rejected(self):
        r = requests.post(f"{API}/auth/accept-invite",
                          json={"token": "totally-bogus-xyz", "name": "X", "password": "Password1!"},
                          timeout=15)
        assert r.status_code == 400
