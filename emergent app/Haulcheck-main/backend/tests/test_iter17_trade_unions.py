"""
Iteration 17 — Trade Unions CRUD tests (Office → Trade Unions).
Endpoints: GET/POST/PUT/DELETE /api/trade-unions, scoped by user_id.
"""
import os
import uuid
import requests
import pytest
from pathlib import Path


def _base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        env_path = Path("/app/frontend/.env")
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base_url()
API = f"{BASE_URL}/api"

SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Test1234!"


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def session():
    return requests.Session()


@pytest.fixture(scope="module")
def token(session):
    r = session.post(f"{API}/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    if r.status_code != 200:
        r = session.post(
            f"{API}/auth/register",
            json={"email": SEED_EMAIL, "password": SEED_PASSWORD, "name": "Fleet Manager"},
            timeout=15,
        )
        assert r.status_code == 200, f"Login/register failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def second_user_headers(session):
    """Create a throwaway 2nd account to verify user_id scoping."""
    email = f"TEST_iso_{uuid.uuid4().hex[:8]}@haulcheck.co.uk"
    r = requests.post(
        f"{API}/auth/register",
        json={"email": email, "password": "Password1!", "name": "TEST Iso"},
        timeout=15,
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


# ---------- Cleanup helper ----------
def _cleanup_all_test_unions(headers):
    """Delete any TEST_ prefixed trade unions left behind."""
    r = requests.get(f"{API}/trade-unions", headers=headers, timeout=15)
    if r.status_code != 200:
        return
    for tu in r.json():
        if tu.get("union_name", "").startswith("TEST_"):
            requests.delete(f"{API}/trade-unions/{tu['id']}", headers=headers, timeout=15)


@pytest.fixture(scope="module", autouse=True)
def cleanup(headers):
    _cleanup_all_test_unions(headers)
    yield
    _cleanup_all_test_unions(headers)


# ---------- Tests ----------
class TestTradeUnionsCRUD:
    """CRUD for /api/trade-unions"""

    def test_list_empty_or_ok(self, headers):
        r = requests.get(f"{API}/trade-unions", headers=headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # ensure no MongoDB _id leaked
        for tu in r.json():
            assert "_id" not in tu

    def test_create_full_payload_and_verify_persistence(self, headers):
        payload = {
            "union_name": f"TEST_Unite_{uuid.uuid4().hex[:6]}",
            "branch": "London Central",
            "rep_name": "Jane Doe",
            "rep_role": "Shop steward",
            "contact_email": "jane@unite.example",
            "contact_phone": "+44 20 7000 0000",
            "membership_number": "M-12345",
            "agreement_ref": "CA-2026-01",
            "notes": "TEST iter17 - full payload",
            "attachments": [],
        }
        r = requests.post(f"{API}/trade-unions", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        created = r.json()

        # data assertions
        for k in ("union_name", "branch", "rep_name", "rep_role", "contact_email",
                 "contact_phone", "membership_number", "agreement_ref", "notes"):
            assert created[k] == payload[k], f"field {k} mismatch"
        assert created["id"].startswith("tu_")
        assert "user_id" in created and created["user_id"]
        assert "_id" not in created
        assert "created_at" in created

        # GET to verify persistence
        r = requests.get(f"{API}/trade-unions", headers=headers, timeout=15)
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()]
        assert created["id"] in ids

        # store for later tests via class attribute
        TestTradeUnionsCRUD.created_id = created["id"]
        TestTradeUnionsCRUD.created_payload = payload

    def test_create_minimal_only_union_name(self, headers):
        payload = {"union_name": f"TEST_MinimalOnly_{uuid.uuid4().hex[:6]}"}
        r = requests.post(f"{API}/trade-unions", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["union_name"] == payload["union_name"]
        assert data["branch"] == ""
        assert data["rep_name"] == ""
        assert data["attachments"] == []
        # cleanup
        requests.delete(f"{API}/trade-unions/{data['id']}", headers=headers, timeout=15)

    def test_create_missing_union_name_rejected(self, headers):
        r = requests.post(f"{API}/trade-unions", headers=headers, json={"branch": "no name"}, timeout=15)
        assert r.status_code in (400, 422), f"expected validation error, got {r.status_code}: {r.text}"

    def test_update_and_verify_persistence(self, headers):
        tid = TestTradeUnionsCRUD.created_id
        updated_payload = dict(TestTradeUnionsCRUD.created_payload)
        updated_payload["rep_name"] = "Updated Rep Name"
        updated_payload["notes"] = "TEST iter17 - updated"

        r = requests.put(f"{API}/trade-unions/{tid}", headers=headers, json=updated_payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # verify via list
        r = requests.get(f"{API}/trade-unions", headers=headers, timeout=15)
        assert r.status_code == 200
        found = next((t for t in r.json() if t["id"] == tid), None)
        assert found is not None
        assert found["rep_name"] == "Updated Rep Name"
        assert found["notes"] == "TEST iter17 - updated"
        # unchanged fields intact
        assert found["union_name"] == TestTradeUnionsCRUD.created_payload["union_name"]
        assert found["membership_number"] == "M-12345"

    def test_update_nonexistent_returns_404(self, headers):
        r = requests.put(
            f"{API}/trade-unions/tu_nonexistent_xyz",
            headers=headers,
            json={"union_name": "TEST_ghost"},
            timeout=15,
        )
        assert r.status_code == 404

    def test_delete_and_verify_removal(self, headers):
        tid = TestTradeUnionsCRUD.created_id
        r = requests.delete(f"{API}/trade-unions/{tid}", headers=headers, timeout=15)
        assert r.status_code == 200
        # verify removal
        r = requests.get(f"{API}/trade-unions", headers=headers, timeout=15)
        ids = [t["id"] for t in r.json()]
        assert tid not in ids


class TestTradeUnionsAuth:
    """Auth & isolation"""

    def test_unauthenticated_get_rejected(self):
        r = requests.get(f"{API}/trade-unions", timeout=15)
        assert r.status_code in (401, 403)

    def test_unauthenticated_post_rejected(self):
        r = requests.post(f"{API}/trade-unions", json={"union_name": "x"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_user_scoping_isolation(self, headers, second_user_headers):
        # user A creates a union
        payload = {"union_name": f"TEST_iso_A_{uuid.uuid4().hex[:6]}"}
        r = requests.post(f"{API}/trade-unions", headers=headers, json=payload, timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]

        # user B should NOT see it
        r = requests.get(f"{API}/trade-unions", headers=second_user_headers, timeout=15)
        assert r.status_code == 200
        b_ids = [t["id"] for t in r.json()]
        assert tid not in b_ids

        # user B cannot update it (404)
        r = requests.put(
            f"{API}/trade-unions/{tid}",
            headers=second_user_headers,
            json={"union_name": "TEST_hijack"},
            timeout=15,
        )
        assert r.status_code == 404

        # cleanup
        requests.delete(f"{API}/trade-unions/{tid}", headers=headers, timeout=15)


class TestOfficeRegression:
    """Smoke test — other Office tab endpoints still respond."""

    def test_insurance_list(self, headers):
        r = requests.get(f"{API}/insurance", headers=headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_documents_list(self, headers):
        r = requests.get(f"{API}/documents", headers=headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_training_list(self, headers):
        r = requests.get(f"{API}/training", headers=headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_links_list(self, headers):
        r = requests.get(f"{API}/links", headers=headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
