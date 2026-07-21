"""Iteration 25 - PMI checklist + rectified_by + auth-bypass regression tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MANAGER_EMAIL = "manager@haulcheck.co.uk"
MANAGER_PWD = "Test1234!"


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": MANAGER_EMAIL, "password": MANAGER_PWD}, timeout=15)
    if r.status_code != 200:
        # Try register then login
        requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": MANAGER_EMAIL, "password": MANAGER_PWD, "full_name": "Manager"}, timeout=15)
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": MANAGER_EMAIL, "password": MANAGER_PWD}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def mgr_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def driver_token(mgr_headers):
    drivers = requests.get(f"{BASE_URL}/api/drivers", headers=mgr_headers, timeout=15).json()
    assert drivers, "no drivers found for manager"
    did = drivers[0]["id"]
    r = requests.post(f"{BASE_URL}/api/drivers/{did}/access-code", headers=mgr_headers, timeout=15)
    assert r.status_code == 200
    code = r.json()["access_code"]
    r = requests.post(f"{BASE_URL}/api/driver/login", json={"code": code}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


# ---------- AUTH REGRESSION ----------

class TestAuthRegression:
    def test_driver_token_rejected_on_manager_vehicles(self, driver_token):
        r = requests.get(f"{BASE_URL}/api/vehicles",
                         headers={"Authorization": f"Bearer {driver_token}"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_driver_token_rejected_on_manager_drivers(self, driver_token):
        r = requests.get(f"{BASE_URL}/api/drivers",
                         headers={"Authorization": f"Bearer {driver_token}"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_driver_token_rejected_on_pmi(self, driver_token):
        r = requests.get(f"{BASE_URL}/api/pmi",
                         headers={"Authorization": f"Bearer {driver_token}"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_manager_token_rejected_on_driver_me(self, mgr_headers):
        r = requests.get(f"{BASE_URL}/api/driver/me", headers=mgr_headers, timeout=15)
        assert r.status_code == 403

    def test_manager_token_works_on_manager_endpoint(self, mgr_headers):
        r = requests.get(f"{BASE_URL}/api/vehicles", headers=mgr_headers, timeout=15)
        assert r.status_code == 200


# ---------- PMI CHECKLIST ----------

@pytest.fixture
def pmi_schedule(mgr_headers):
    """Create a TEST PMI schedule + cleanup."""
    veh = requests.get(f"{BASE_URL}/api/vehicles", headers=mgr_headers, timeout=15).json()
    assert veh, "need at least one vehicle"
    reg = veh[0]["registration"]
    body = {"vehicle_reg": reg, "frequency_weeks": 6, "next_due": "2026-06-01",
            "inspector": "TEST inspector", "notes": "TEST"}
    r = requests.post(f"{BASE_URL}/api/pmi", headers=mgr_headers, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    sched = r.json()
    yield sched
    # cleanup: delete records for this sched then sched
    recs = requests.get(f"{BASE_URL}/api/pmi/records", headers=mgr_headers, timeout=15).json()
    for rec in recs:
        if rec.get("pmi_id") == sched["id"]:
            requests.delete(f"{BASE_URL}/api/pmi/records/{rec['id']}", headers=mgr_headers, timeout=15)
    requests.delete(f"{BASE_URL}/api/pmi/{sched['id']}", headers=mgr_headers, timeout=15)


def _build_checklist(defect_indexes=()):
    items = []
    idx = 0
    sections = [
        ("A: Inside cab", 22),
        ("B: Ground level & under-vehicle", 42),
        ("C: Brake performance", 3),
    ]
    for sec, count in sections:
        for i in range(count):
            defect = idx in defect_indexes
            items.append({"section": sec, "item": f"item-{idx}",
                          "ok": not defect,
                          "note": ("brake noise" if defect else "")})
            idx += 1
    return items


class TestPMIComplete:
    def test_complete_persists_checklist_and_rectified_by(self, mgr_headers, pmi_schedule):
        checklist = _build_checklist(defect_indexes=(0, 3))
        payload = {
            "inspection_date": "2026-01-15",
            "result": "fail",  # frontend already derives fail on defects
            "inspector": "TEST inspector",
            "rectified_by": "TEST J. Workshop",
            "notes": "item-0: brake noise; item-3: brake noise",
            "checklist": checklist,
        }
        r = requests.post(f"{BASE_URL}/api/pmi/{pmi_schedule['id']}/complete",
                          headers=mgr_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("next_due")  # rescheduled

        # Verify persisted via GET /api/pmi/records
        recs = requests.get(f"{BASE_URL}/api/pmi/records", headers=mgr_headers, timeout=15).json()
        matched = [x for x in recs if x.get("pmi_id") == pmi_schedule["id"]]
        assert matched, "PMI record not persisted"
        rec = matched[0]
        assert rec["rectified_by"] == "TEST J. Workshop"
        assert isinstance(rec.get("checklist"), list)
        assert len(rec["checklist"]) == 67
        defects = [c for c in rec["checklist"] if not c.get("ok")]
        assert len(defects) == 2
        assert rec["result"] == "fail"

    def test_next_due_updates(self, mgr_headers, pmi_schedule):
        r = requests.post(f"{BASE_URL}/api/pmi/{pmi_schedule['id']}/complete",
                          headers=mgr_headers,
                          json={"inspection_date": "2026-02-01", "result": "pass",
                                "inspector": "x", "rectified_by": "",
                                "checklist": _build_checklist()}, timeout=15)
        assert r.status_code == 200
        assert r.json()["next_due"]  # 6 wks after 2026-02-01

    def test_history_pdf_returns_pdf(self, mgr_headers, pmi_schedule):
        # first make sure at least one record
        requests.post(f"{BASE_URL}/api/pmi/{pmi_schedule['id']}/complete",
                      headers=mgr_headers,
                      json={"inspection_date": "2026-01-20", "result": "pass",
                            "inspector": "x", "rectified_by": "TEST rectifier",
                            "checklist": _build_checklist(defect_indexes=(1,))}, timeout=20)
        r = requests.get(f"{BASE_URL}/api/pmi/{pmi_schedule['id']}/report",
                         headers=mgr_headers, timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "response body is not a PDF"
        assert len(r.content) > 500
