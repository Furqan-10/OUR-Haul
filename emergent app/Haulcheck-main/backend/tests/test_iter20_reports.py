"""Iteration 20 - PDF report endpoints and Vehicle type field.

Covers:
  * POST /api/vehicles with `type` and PUT persistence
  * GET /api/reports/{kind} for vehicles, trailers, drivers, defects, service,
    wheel, walkaround, pmi (200 + application/pdf)
  * GET /api/pmi/{pid}/report (per-schedule history PDF)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")

EMAIL = "manager@haulcheck.co.uk"
PASSWORD = "Test1234!"

REPORT_KINDS = ["vehicles", "trailers", "drivers", "defects", "service", "wheel", "walkaround", "pmi"]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        # Try register (idempotent seed)
        requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": EMAIL, "password": PASSWORD, "name": "Manager", "role": "manager"
        }, timeout=30)
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# ---------- Report endpoints (PDF) ----------
@pytest.mark.parametrize("kind", REPORT_KINDS)
def test_report_returns_pdf(client, kind):
    r = client.get(f"{BASE_URL}/api/reports/{kind}", timeout=60)
    assert r.status_code == 200, f"/reports/{kind}: {r.status_code} {r.text[:200]}"
    ct = r.headers.get("content-type", "")
    assert "application/pdf" in ct, f"/reports/{kind}: content-type={ct}"
    assert r.content[:4] == b"%PDF", f"/reports/{kind}: not a PDF (starts with {r.content[:8]!r})"
    assert len(r.content) > 500, f"/reports/{kind}: PDF too small ({len(r.content)} bytes)"


def test_report_unknown_kind_404(client):
    r = client.get(f"{BASE_URL}/api/reports/does-not-exist", timeout=15)
    assert r.status_code == 404


def test_report_requires_auth():
    r = requests.get(f"{BASE_URL}/api/reports/vehicles", timeout=15)
    assert r.status_code in (401, 403)


# ---------- PMI per-schedule history report ----------
def test_pmi_history_report(client):
    schedules = client.get(f"{BASE_URL}/api/pmi", timeout=15).json()
    assert isinstance(schedules, list)
    if not schedules:
        pytest.skip("No PMI schedules available for manager account")
    pid = schedules[0]["id"]
    r = client.get(f"{BASE_URL}/api/pmi/{pid}/report", timeout=60)
    assert r.status_code == 200, f"pmi report: {r.status_code} {r.text[:200]}"
    assert "application/pdf" in r.headers.get("content-type", "")
    assert r.content[:4] == b"%PDF"


def test_pmi_history_unknown_id(client):
    r = client.get(f"{BASE_URL}/api/pmi/pmi_does_not_exist_zzz/report", timeout=15)
    assert r.status_code == 404


# ---------- Vehicle `type` field persistence ----------
class TestVehicleType:
    """Verify create + update with `type` persists correctly."""

    created_id = None

    def test_create_with_type_lgv(self, client):
        payload = {
            "registration": f"TEST_T{os.urandom(2).hex().upper()}",
            "make": "Ford", "model": "Transit",
            "type": "LGV / Van",
        }
        r = client.post(f"{BASE_URL}/api/vehicles", json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data.get("type") == "LGV / Van"
        assert data.get("registration") == payload["registration"]
        TestVehicleType.created_id = data["id"]

        # GET verify persistence
        g = client.get(f"{BASE_URL}/api/vehicles", timeout=15)
        assert g.status_code == 200
        row = next((v for v in g.json() if v["id"] == data["id"]), None)
        assert row is not None
        assert row["type"] == "LGV / Van"

    def test_update_type_to_car(self, client):
        vid = TestVehicleType.created_id
        assert vid, "prerequisite test_create_with_type_lgv must pass first"
        # Fetch current row and PUT with type changed
        rows = client.get(f"{BASE_URL}/api/vehicles", timeout=15).json()
        row = next(v for v in rows if v["id"] == vid)
        payload = {k: row.get(k) for k in ["registration", "make", "model", "type", "mot_due",
                                            "service_due", "tax_due", "first_use_date",
                                            "tacho_calibration_due", "speed_limiter_due",
                                            "vor", "vor_reason", "notes"]}
        payload["type"] = "Car"
        r = client.put(f"{BASE_URL}/api/vehicles/{vid}", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        # GET verify
        rows2 = client.get(f"{BASE_URL}/api/vehicles", timeout=15).json()
        row2 = next(v for v in rows2 if v["id"] == vid)
        assert row2["type"] == "Car"

    def test_cleanup_delete(self, client):
        vid = TestVehicleType.created_id
        if not vid:
            pytest.skip("nothing to delete")
        r = client.delete(f"{BASE_URL}/api/vehicles/{vid}", timeout=15)
        assert r.status_code in (200, 204)
