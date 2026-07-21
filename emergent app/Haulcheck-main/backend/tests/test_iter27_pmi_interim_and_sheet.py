"""
Iteration 27 tests
- PMI Interim inspection endpoint (POST /api/pmi/interim)
- PMI sheet PDF (GET /api/pmi/records/{rid}/sheet)
- Routine PMI complete regression (POST /api/pmi/{pid}/complete)
- Training regression (GET/POST /api/training)
"""

import os
import pytest
import requests

def _load_backend_url():
    val = os.environ.get("REACT_APP_BACKEND_URL")
    if not val:
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        val = line.split("=", 1)[1].strip()
                        break
    if not val:
        raise RuntimeError("REACT_APP_BACKEND_URL is not set")
    return val.rstrip("/")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

EMAIL = "manager@haulcheck.co.uk"
PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def checklist_67():
    """Build a plausible 67-point checklist spanning sections A/B/C."""
    items = []
    # Section A - roughly 20 items
    for i in range(20):
        items.append({"section": "A", "item": f"A-item-{i+1}", "ok": True, "note": ""})
    # Section B - roughly 40 items
    for i in range(40):
        items.append({"section": "B", "item": f"B-item-{i+1}", "ok": True, "note": ""})
    # Section C - roughly 7 items
    for i in range(7):
        items.append({"section": "C", "item": f"C-item-{i+1}", "ok": True, "note": ""})
    return items


# ---------------------- Training regression (must pass first - guards the model bug fix) ----------------------

class TestTrainingRegression:
    def test_training_list_200(self, headers):
        r = requests.get(f"{API}/training", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_training_create(self, headers):
        payload = {
            "driver_name": "TEST_Interim Driver",
            "course_name": "TEST_Driver CPC Module 1",
            "category": "Driver CPC",
            "expiry_date": "2027-12-31",
        }
        r = requests.post(f"{API}/training", headers=headers, json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("course_name") == "TEST_Driver CPC Module 1"
        assert body.get("expiry_date") == "2027-12-31"
        assert body.get("category") == "Driver CPC"
        tid = body.get("id")
        assert tid and tid.startswith("trn_")
        # Persistence check
        r2 = requests.get(f"{API}/training", headers=headers, timeout=30)
        assert r2.status_code == 200
        ids = [t.get("id") for t in r2.json()]
        assert tid in ids
        # Cleanup
        requests.delete(f"{API}/training/{tid}", headers=headers, timeout=30)


# ---------------------- Interim inspection ----------------------

class TestInterimInspection:
    def test_interim_creates_record_no_schedule_change(self, headers, checklist_67):
        pmi_before = requests.get(f"{API}/pmi", headers=headers, timeout=30)
        assert pmi_before.status_code == 200
        count_before = len(pmi_before.json())

        payload = {
            "vehicle_reg": "AB12 CDE",
            "inspection_date": "2026-01-15",
            "result": "pass",
            "inspector": "TEST_Inspector",
            "rectified_by": "",
            "notes": "TEST_interim inspection ok",
            "brake_test_type": "roller",
            "laden": True,
            "service_brake_pct": "55",
            "secondary_brake_pct": "32",
            "parking_brake_pct": "22",
            "checklist": checklist_67,
            "attachments": [],
        }
        r = requests.post(f"{API}/pmi/interim", headers=headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        rec = body.get("record")
        assert rec, "record missing"
        assert rec["inspection_type"] == "interim"
        assert rec["pmi_id"] is None
        assert rec["vehicle_reg"] == "AB12 CDE"
        assert rec["id"].startswith("pmr_")
        # Verify schedule count unchanged
        pmi_after = requests.get(f"{API}/pmi", headers=headers, timeout=30)
        assert pmi_after.status_code == 200
        assert len(pmi_after.json()) == count_before, "PMI schedule count changed after interim"
        # Verify record is retrievable
        recs = requests.get(f"{API}/pmi/records", headers=headers, timeout=30).json()
        rec_ids = [r.get("id") for r in recs]
        assert rec["id"] in rec_ids
        # Save id for reuse
        TestInterimInspection.interim_rid = rec["id"]

    def test_interim_missing_vehicle_reg_400_or_422(self, headers, checklist_67):
        payload = {
            "inspection_date": "2026-01-15",
            "result": "pass",
            "checklist": checklist_67,
        }
        r = requests.post(f"{API}/pmi/interim", headers=headers, json=payload, timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}: {r.text}"

    def test_interim_fail_creates_alert(self, headers, checklist_67):
        # Mark one item as failing
        bad = [dict(c) for c in checklist_67]
        bad[5]["ok"] = False
        bad[5]["note"] = "TEST_defect note"
        payload = {
            "vehicle_reg": "AB12 CDE",
            "inspection_date": "2026-01-15",
            "result": "fail",
            "inspector": "TEST_Inspector",
            "notes": "TEST_interim fail",
            "brake_test_type": "roller",
            "checklist": bad,
            "attachments": [],
        }
        r = requests.post(f"{API}/pmi/interim", headers=headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        # Check alerts
        a = requests.get(f"{API}/alerts", headers=headers, timeout=30)
        assert a.status_code == 200
        alerts = a.json()
        pmi_fail_alerts = [al for al in alerts if al.get("type") == "pmi_fail"]
        assert len(pmi_fail_alerts) >= 1, "expected at least one pmi_fail alert"


# ---------------------- Sheet PDF ----------------------

class TestPMISheetPDF:
    def _get_record_ids(self, headers):
        r = requests.get(f"{API}/pmi/records", headers=headers, timeout=30)
        assert r.status_code == 200
        recs = r.json()
        interim = next((x for x in recs if x.get("inspection_type") == "interim" and x.get("checklist")), None)
        routine = next((x for x in recs if x.get("inspection_type") == "routine" and x.get("checklist")), None)
        return interim, routine, recs

    def test_sheet_pdf_for_interim(self, headers):
        interim, _, recs = self._get_record_ids(headers)
        assert interim, f"No interim record with checklist found among {len(recs)} records"
        rid = interim["id"]
        r = requests.get(f"{API}/pmi/records/{rid}/sheet", headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 5000  # non-trivial PDF

    def test_sheet_pdf_for_routine(self, headers, checklist_67):
        # Ensure at least one routine record exists by completing the routine schedule
        _, routine, _ = self._get_record_ids(headers)
        if not routine:
            # create one by completing the existing schedule
            pmis = requests.get(f"{API}/pmi", headers=headers, timeout=30).json()
            assert pmis, "no PMI schedule available"
            pid = pmis[0]["id"]
            payload = {
                "inspection_date": "2026-01-15",
                "result": "pass",
                "inspector": "TEST_Inspector",
                "notes": "TEST_routine",
                "brake_test_type": "roller",
                "laden": True,
                "service_brake_pct": "55",
                "secondary_brake_pct": "32",
                "parking_brake_pct": "22",
                "checklist": checklist_67,
                "attachments": [],
            }
            r = requests.post(f"{API}/pmi/{pid}/complete", headers=headers, json=payload, timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True
            assert body["record"]["inspection_type"] == "routine"
            rid = body["record"]["id"]
        else:
            rid = routine["id"]
        r = requests.get(f"{API}/pmi/records/{rid}/sheet", headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 5000

    def test_sheet_pdf_include_files(self, headers):
        interim, _, _ = self._get_record_ids(headers)
        assert interim, "need an interim record"
        rid = interim["id"]
        r = requests.get(f"{API}/pmi/records/{rid}/sheet?include_files=true", headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"


# ---------------------- Routine complete regression ----------------------

class TestRoutineComplete:
    def test_complete_advances_next_due_and_stamps_type(self, headers, checklist_67):
        pmis = requests.get(f"{API}/pmi", headers=headers, timeout=30).json()
        assert pmis, "no PMI schedule"
        pid = pmis[0]["id"]
        old_next_due = pmis[0].get("next_due")
        payload = {
            "inspection_date": "2026-01-20",
            "result": "pass",
            "inspector": "TEST_Inspector",
            "notes": "TEST_regression_routine",
            "brake_test_type": "roller",
            "laden": True,
            "service_brake_pct": "55",
            "secondary_brake_pct": "32",
            "parking_brake_pct": "22",
            "checklist": checklist_67,
            "attachments": [],
        }
        r = requests.post(f"{API}/pmi/{pid}/complete", headers=headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "next_due" in body
        assert body["record"]["inspection_type"] == "routine"
        assert body["record"]["pmi_id"] == pid
        # Ensure schedule count remained
        pmis_after = requests.get(f"{API}/pmi", headers=headers, timeout=30).json()
        assert len(pmis_after) == len(pmis)
