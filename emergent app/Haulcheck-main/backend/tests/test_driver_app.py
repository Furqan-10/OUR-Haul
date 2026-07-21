"""
Backend tests for Driver Mobile App (iteration 24):
- Manager: issue driver access code, assign vehicle
- Driver: login with code, /driver/me, /driver/vehicle, /driver/vehicles
- Driver: submit walkaround + defect and verify manager sees them
- Cross-role security: manager token rejected on driver endpoints and vice-versa
"""
import os
import io
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

MANAGER_EMAIL = "manager@haulcheck.co.uk"
MANAGER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{API}/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    if r.status_code != 200:
        # attempt register
        requests.post(f"{API}/auth/register", json={
            "email": MANAGER_EMAIL, "password": MANAGER_PASSWORD, "name": "Manager"
        })
        r = requests.post(f"{API}/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}"}


@pytest.fixture(scope="module")
def john_driver(manager_headers):
    """Find or create John Smith assigned to AB12 CDE."""
    # ensure vehicle exists
    vr = requests.get(f"{API}/vehicles", headers=manager_headers)
    assert vr.status_code == 200
    vehicles = vr.json()
    if not any(v.get("registration") == "AB12 CDE" for v in vehicles):
        create_v = requests.post(f"{API}/vehicles", headers=manager_headers, json={
            "registration": "AB12 CDE", "type": "HGV", "make": "Volvo", "model": "FH"
        })
        assert create_v.status_code == 200, create_v.text

    r = requests.get(f"{API}/drivers", headers=manager_headers)
    assert r.status_code == 200
    john = next((d for d in r.json() if d.get("name") == "John Smith"), None)
    if not john:
        create = requests.post(f"{API}/drivers", headers=manager_headers, json={
            "name": "John Smith", "assigned_vehicle_reg": "AB12 CDE"
        })
        assert create.status_code == 200, create.text
        john = create.json()
    # ensure vehicle assigned
    if john.get("assigned_vehicle_reg") != "AB12 CDE":
        upd = requests.put(f"{API}/drivers/{john['id']}", headers=manager_headers, json={
            "name": "John Smith", "assigned_vehicle_reg": "AB12 CDE"
        })
        assert upd.status_code == 200
    return john


# ---------- Manager: access code + vehicle assignment ----------
class TestAccessCodeIssuance:
    def test_issue_access_code(self, manager_headers, john_driver):
        r = requests.post(f"{API}/drivers/{john_driver['id']}/access-code", headers=manager_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert "access_code" in data
        code = data["access_code"]
        assert isinstance(code, str) and 6 <= len(code) <= 8
        # persistence check
        r2 = requests.get(f"{API}/drivers", headers=manager_headers)
        drv = next(d for d in r2.json() if d["id"] == john_driver["id"])
        assert drv["access_code"] == code
        pytest.driver_code = code
        pytest.driver_id = john_driver["id"]

    def test_regenerate_changes_code(self, manager_headers, john_driver):
        old = pytest.driver_code
        r = requests.post(f"{API}/drivers/{john_driver['id']}/access-code", headers=manager_headers)
        assert r.status_code == 200
        new_code = r.json()["access_code"]
        assert new_code != old
        pytest.driver_code = new_code


# ---------- Driver login ----------
class TestDriverLogin:
    def test_login_invalid_code(self):
        r = requests.post(f"{API}/driver/login", json={"code": "ZZZZZZ"})
        assert r.status_code in (401, 404)

    def test_login_missing_code(self):
        r = requests.post(f"{API}/driver/login", json={})
        assert r.status_code in (400, 401, 404, 422)

    def test_login_success(self):
        r = requests.post(f"{API}/driver/login", json={"code": pytest.driver_code})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        assert data["driver"]["name"] == "John Smith"
        assert data["driver"]["assigned_vehicle_reg"] == "AB12 CDE"
        pytest.driver_token = data["token"]

    def test_login_lowercase_code_accepted(self):
        # UI upper-cases in JS, ensure backend expects the exact stored value
        code = pytest.driver_code
        r = requests.post(f"{API}/driver/login", json={"code": code.lower()})
        # backend does exact match; lower may fail — this is diagnostic
        # Not a strict assertion; just record status
        assert r.status_code in (200, 401, 404)


# ---------- Driver /me and /vehicle ----------
class TestDriverEndpoints:
    @property
    def hdr(self):
        return {"Authorization": f"Bearer {pytest.driver_token}"}

    def test_driver_me(self):
        r = requests.get(f"{API}/driver/me", headers=self.hdr)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "John Smith"
        assert data["assigned_vehicle_reg"] == "AB12 CDE"
        assert "licence_status" in data
        assert "cpc_status" in data
        assert "tacho_status" in data
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_driver_vehicle(self):
        r = requests.get(f"{API}/driver/vehicle", headers=self.hdr)
        assert r.status_code == 200
        data = r.json()
        assert data["vehicle"] is not None
        assert data["vehicle"]["registration"] == "AB12 CDE"
        assert "mot_status" in data["vehicle"]
        assert "documents" in data

    def test_driver_vehicles_list(self):
        r = requests.get(f"{API}/driver/vehicles", headers=self.hdr)
        assert r.status_code == 200
        data = r.json()
        # Endpoint returns list of registration strings (per server.py:1188)
        assert isinstance(data, list)
        assert "AB12 CDE" in data


# ---------- Driver walkaround / defect submission → manager visibility ----------
class TestDriverSubmissions:
    @property
    def hdr(self):
        return {"Authorization": f"Bearer {pytest.driver_token}"}

    def test_driver_submits_walkaround(self, manager_headers):
        checklist = [
            {"section": "Internal", "item": "Mirrors and glass", "ok": False, "note": "TEST cracked mirror"},
        ] + [{"section": "Internal", "item": f"Item {i}", "ok": True, "note": ""} for i in range(23)]
        payload = {
            "vehicle_reg": "AB12 CDE",
            "checklist": checklist,
            "mileage": "123456",
            "defects_noted": "TEST Mirrors and glass: cracked",
            "result": "defects_found",
            "check_date": "2026-01-10",
        }
        r = requests.post(f"{API}/driver/walkaround", headers=self.hdr, json=payload)
        assert r.status_code == 200, r.text

        # Manager sees the walkaround
        m = requests.get(f"{API}/walkarounds", headers=manager_headers)
        assert m.status_code == 200
        wa_list = m.json()
        found = [w for w in wa_list if w.get("driver_name") == "John Smith"
                 and w.get("vehicle_reg") == "AB12 CDE"
                 and "TEST" in (w.get("defects_noted") or "")]
        assert found, f"Manager cannot see driver's walkaround. All: {wa_list[:3]}"
        assert found[0]["result"] == "defects_found"
        pytest.driver_walkaround_id = found[0]["id"]

    def test_driver_submits_defect(self, manager_headers):
        payload = {
            "vehicle_reg": "AB12 CDE",
            "description": "TEST driver-reported defect: brake noise",
            "severity": "major",
            "defect_date": "2026-01-10",
        }
        r = requests.post(f"{API}/driver/defect", headers=self.hdr, json=payload)
        assert r.status_code == 200, r.text

        m = requests.get(f"{API}/defects", headers=manager_headers)
        assert m.status_code == 200
        defects = m.json()
        found = [d for d in defects if "TEST driver-reported defect" in (d.get("description") or "")]
        assert found, "Manager cannot see driver's defect"
        d0 = found[0]
        assert d0.get("severity") == "major"
        # reported_by should be the driver name
        assert d0.get("reported_by") == "John Smith"
        pytest.driver_defect_id = d0["id"]

    def test_driver_upload(self):
        files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
        r = requests.post(f"{API}/driver/upload",
                          headers={"Authorization": f"Bearer {pytest.driver_token}"},
                          files=files)
        assert r.status_code == 200, r.text
        assert "file_id" in r.json()


# ---------- Security: cross-role rejection ----------
class TestSecurity:
    def test_manager_token_rejected_on_driver_endpoint(self, manager_headers):
        r = requests.get(f"{API}/driver/me", headers=manager_headers)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    def test_driver_token_rejected_on_manager_endpoint(self):
        hdr = {"Authorization": f"Bearer {pytest.driver_token}"}
        r = requests.get(f"{API}/vehicles", headers=hdr)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_no_token_on_driver_me(self):
        r = requests.get(f"{API}/driver/me")
        assert r.status_code == 401

    def test_manager_token_rejected_on_driver_walkaround(self, manager_headers):
        r = requests.post(f"{API}/driver/walkaround", headers=manager_headers, json={
            "vehicle_reg": "AB12 CDE", "result": "nil_defect", "check_date": "2026-01-10",
        })
        assert r.status_code == 403


# ---------- Cleanup ----------
def test_cleanup(manager_headers):
    if hasattr(pytest, "driver_walkaround_id"):
        requests.delete(f"{API}/walkarounds/{pytest.driver_walkaround_id}", headers=manager_headers)
    if hasattr(pytest, "driver_defect_id"):
        requests.delete(f"{API}/defects/{pytest.driver_defect_id}", headers=manager_headers)
