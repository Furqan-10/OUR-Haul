"""
New compliance feature backend tests (iteration 12):
- Walkaround / Daily Checks CRUD (/api/walkarounds)
- Test History / Prohibitions CRUD (/api/test-history)
- Defect Rectification PUT /api/defects/{id}/rectify
- Wheel Security Audits CRUD (/api/wheel-audits)
- New document types (Attestation Record, Indoctrination Document, Driver Infringement,
  Adhoc Note, Warning Letter, Infringement Report)
- AI Gap-Detection Audit checklist surfaces new areas
- PMI brake test fields (roller/decelerometer + laden + %s) persisted
- Export & Reminders smoke tests
"""
import os
import uuid
import requests
import pytest
from datetime import date, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
API = f"{BASE_URL}/api"
SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Test1234!"

TODAY = date.today().isoformat()
FUTURE_VALID = (date.today() + timedelta(days=120)).isoformat()
FUTURE_DUE_SOON = (date.today() + timedelta(days=15)).isoformat()
PAST_EXPIRED = (date.today() - timedelta(days=30)).isoformat()


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    if r.status_code == 200:
        return r.json()["token"]
    r = requests.post(f"{API}/auth/register", json={"email": SEED_EMAIL, "password": SEED_PASSWORD, "name": "Fleet Manager"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Walkaround Checks ----------
class TestWalkarounds:
    def test_requires_auth(self):
        assert requests.get(f"{API}/walkarounds", timeout=15).status_code == 401
        assert requests.post(f"{API}/walkarounds", json={"vehicle_reg": "X"}, timeout=15).status_code == 401
        assert requests.delete(f"{API}/walkarounds/x", timeout=15).status_code == 401

    def test_crud_lifecycle(self, h):
        reg = f"TEST-W{uuid.uuid4().hex[:5].upper()}"
        payload = {
            "vehicle_reg": reg,
            "driver_name": f"TEST Driver {uuid.uuid4().hex[:4]}",
            "check_date": TODAY,
            "result": "defects_found",
            "mileage": "123456",
            "defects_noted": "TEST: wiper blade damaged; tyre pressure NSF low",
        }
        r = requests.post(f"{API}/walkarounds", json=payload, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        w = r.json()
        assert w["vehicle_reg"] == reg
        assert w["driver_name"] == payload["driver_name"]
        assert w["result"] == "defects_found"
        assert w["mileage"] == "123456"
        assert w["defects_noted"] == payload["defects_noted"]
        assert w["id"].startswith("wac_")
        wid = w["id"]

        # List: persisted
        r = requests.get(f"{API}/walkarounds", headers=h, timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        item = next((x for x in items if x["id"] == wid), None)
        assert item is not None
        assert item["defects_noted"] == payload["defects_noted"]

        # Edit
        edit = {**payload, "result": "nil_defect", "defects_noted": ""}
        r = requests.put(f"{API}/walkarounds/{wid}", json=edit, headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/walkarounds", headers=h, timeout=15)
        item = next(x for x in r.json() if x["id"] == wid)
        assert item["result"] == "nil_defect"
        assert item["defects_noted"] == ""

        # Delete
        r = requests.delete(f"{API}/walkarounds/{wid}", headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/walkarounds", headers=h, timeout=15)
        assert not any(x["id"] == wid for x in r.json())

    def test_edit_missing_returns_404(self, h):
        r = requests.put(f"{API}/walkarounds/nonexistent", json={"vehicle_reg": "X"}, headers=h, timeout=15)
        assert r.status_code == 404


# ---------- Test History / Prohibitions ----------
class TestTestHistory:
    def test_requires_auth(self):
        assert requests.get(f"{API}/test-history", timeout=15).status_code == 401
        assert requests.post(f"{API}/test-history", json={"vehicle_reg": "X"}, timeout=15).status_code == 401

    def test_crud_lifecycle(self, h):
        reg = f"TEST-TH{uuid.uuid4().hex[:5].upper()}"
        payload = {
            "vehicle_reg": reg,
            "event_type": "prohibition",
            "event_date": TODAY,
            "result": "pg9",
            "reference": "PG9-TEST-99988",
            "notes": "TEST: PG9 prohibition for brake imbalance",
        }
        r = requests.post(f"{API}/test-history", json=payload, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["vehicle_reg"] == reg
        assert t["event_type"] == "prohibition"
        assert t["result"] == "pg9"
        assert t["reference"] == payload["reference"]
        assert t["id"].startswith("thr_")
        tid = t["id"]

        r = requests.get(f"{API}/test-history", headers=h, timeout=15)
        assert r.status_code == 200
        item = next((x for x in r.json() if x["id"] == tid), None)
        assert item is not None
        assert item["notes"] == payload["notes"]

        # Edit
        edit = {**payload, "event_type": "annual_test", "result": "pass", "notes": "cleared"}
        r = requests.put(f"{API}/test-history/{tid}", json=edit, headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/test-history", headers=h, timeout=15)
        item = next(x for x in r.json() if x["id"] == tid)
        assert item["event_type"] == "annual_test"
        assert item["result"] == "pass"

        # Delete
        r = requests.delete(f"{API}/test-history/{tid}", headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/test-history", headers=h, timeout=15)
        assert not any(x["id"] == tid for x in r.json())

    def test_edit_missing_returns_404(self, h):
        r = requests.put(f"{API}/test-history/nonexistent", json={"vehicle_reg": "X"}, headers=h, timeout=15)
        assert r.status_code == 404


# ---------- Defect Rectification ----------
class TestDefectRectify:
    def test_rectify_marks_and_persists(self, h):
        # Create a defect
        payload = {
            "vehicle_reg": f"TEST-DR{uuid.uuid4().hex[:4].upper()}",
            "reported_by": "TEST Reporter",
            "category": "Tyres",
            "severity": "major",
            "description": "TEST: NSF tyre tread below 1mm",
        }
        r = requests.post(f"{API}/defects", json=payload, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        did = d["id"]
        assert d["status"] == "open"

        # Rectify
        rect = {
            "rectified_date": TODAY,
            "rectified_by": "TEST Mechanic",
            "rectification_notes": "Replaced tyre with new Michelin, torqued to spec.",
        }
        r = requests.put(f"{API}/defects/{did}/rectify", json=rect, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # GET verify persistence
        r = requests.get(f"{API}/defects", headers=h, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["status"] == "rectified"
        assert item["rectified_date"] == TODAY
        assert item["rectified_by"] == "TEST Mechanic"
        assert "Replaced tyre" in item["rectification_notes"]

        # Cleanup
        requests.delete(f"{API}/defects/{did}", headers=h, timeout=15)

    def test_rectify_missing_returns_404(self, h):
        r = requests.put(f"{API}/defects/nonexistent/rectify",
                         json={"rectified_date": TODAY, "rectified_by": "X", "rectification_notes": "x"},
                         headers=h, timeout=15)
        assert r.status_code == 404

    def test_rectify_requires_auth(self):
        r = requests.put(f"{API}/defects/x/rectify", json={"rectified_by": "x"}, timeout=15)
        assert r.status_code == 401


# ---------- Wheel Security Audits ----------
class TestWheelAudits:
    def test_requires_auth(self):
        assert requests.get(f"{API}/wheel-audits", timeout=15).status_code == 401

    def test_crud_lifecycle_and_status_computed(self, h):
        reg = f"TEST-WS{uuid.uuid4().hex[:4].upper()}"
        payload = {
            "vehicle_reg": reg,
            "audit_date": TODAY,
            "result": "pass",
            "torque_setting": "600 Nm",
            "checked_by": "TEST Fitter",
            "next_due": FUTURE_DUE_SOON,  # 15d -> due_soon
            "notes": "TEST: wheel security audit",
        }
        r = requests.post(f"{API}/wheel-audits", json=payload, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        w = r.json()
        assert w["vehicle_reg"] == reg
        assert w["torque_setting"] == "600 Nm"
        assert w["id"].startswith("wsa_")
        wid = w["id"]

        # List: status is computed
        r = requests.get(f"{API}/wheel-audits", headers=h, timeout=15)
        item = next(x for x in r.json() if x["id"] == wid)
        assert item["status"] == "due_soon"
        assert item["days_left"] is not None and item["days_left"] <= 30

        # Edit -> expired
        edit = {**payload, "next_due": PAST_EXPIRED}
        r = requests.put(f"{API}/wheel-audits/{wid}", json=edit, headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/wheel-audits", headers=h, timeout=15)
        item = next(x for x in r.json() if x["id"] == wid)
        assert item["status"] == "expired"

        # Dashboard should include wheel alert (expired) and counts
        r = requests.get(f"{API}/dashboard", headers=h, timeout=15)
        body = r.json()
        wheel_alerts = [a for a in body["alerts"] if a.get("type") == "wheel" and a.get("name") == reg]
        assert wheel_alerts and wheel_alerts[0]["status"] == "expired"

        # Calendar contains wheel event
        r = requests.get(f"{API}/calendar", headers=h, timeout=15)
        assert any(e.get("type") == "wheel" and reg in e.get("title", "") for e in r.json())

        # Delete
        r = requests.delete(f"{API}/wheel-audits/{wid}", headers=h, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/wheel-audits", headers=h, timeout=15)
        assert not any(x["id"] == wid for x in r.json())

    def test_edit_missing_returns_404(self, h):
        r = requests.put(f"{API}/wheel-audits/nonexistent", json={"vehicle_reg": "X"}, headers=h, timeout=15)
        assert r.status_code == 404


# ---------- New Document Types ----------
class TestNewDocumentTypes:
    NEW_TYPES = [
        "Attestation Record", "Indoctrination Document", "Driver Infringement",
        "Adhoc Note", "Warning Letter", "Infringement Report",
    ]

    def test_create_all_new_doc_types(self, h):
        created = []
        try:
            for t in self.NEW_TYPES:
                payload = {
                    "title": f"TEST {t} {uuid.uuid4().hex[:4]}",
                    "doc_type": t,
                    "reference": f"REF-{uuid.uuid4().hex[:5]}",
                    "expiry_date": FUTURE_VALID,
                    "notes": f"TEST doc of type {t}",
                }
                r = requests.post(f"{API}/documents", json=payload, headers=h, timeout=15)
                assert r.status_code == 200, f"{t}: {r.text}"
                body = r.json()
                assert body["doc_type"] == t, f"Expected {t}, got {body['doc_type']}"
                created.append(body["id"])

            # Verify persistence
            r = requests.get(f"{API}/documents", headers=h, timeout=15)
            docs = r.json()
            saved_types = {d["doc_type"] for d in docs if d["id"] in created}
            assert saved_types == set(self.NEW_TYPES)
        finally:
            for did in created:
                requests.delete(f"{API}/documents/{did}", headers=h, timeout=15)


# ---------- AI Gap Detection (new areas) ----------
class TestGapDetection:
    def test_gap_checklist_covers_new_areas(self, h):
        # Create an isolated user so we know exactly which gaps to expect
        email = f"TEST_gap_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "TEST Gap"}, timeout=15)
        assert r.status_code == 200
        hh = {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}

        # Add a vehicle so per-vehicle checks trigger
        reg = f"TEST-GAP{uuid.uuid4().hex[:4].upper()}"
        rv = requests.post(f"{API}/vehicles", json={"registration": reg, "make": "DAF", "model": "XF", "type": "HGV"}, headers=hh, timeout=15)
        assert rv.status_code == 200

        # Run AI risk-insight which returns the gap checklist (even if AI fails, checklist is generated)
        r = requests.post(f"{API}/ai/risk-insight", headers=hh, timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert "checklist" in body and isinstance(body["checklist"], list)
        items = " ".join(g["item"] for g in body["checklist"])
        # Should include the new compliance areas for the vehicle
        assert "wheel security audit" in items.lower(), f"Missing wheel security gap. Items:\n{items}"
        assert "walkaround" in items.lower(), f"Missing walkaround gap. Items:\n{items}"
        assert "annual test" in items.lower() or "prohibition history" in items.lower(), f"Missing test history gap. Items:\n{items}"

        # Cleanup
        rv = requests.get(f"{API}/vehicles", headers=hh, timeout=15).json()
        for v in rv:
            requests.delete(f"{API}/vehicles/{v['id']}", headers=hh, timeout=15)


# ---------- PMI brake-test fields ----------
class TestPMIBrakeTest:
    def test_brake_test_persisted_on_complete(self, h):
        reg = f"TEST-BR{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/pmi", json={"vehicle_reg": reg, "frequency_weeks": 6, "next_due": FUTURE_DUE_SOON, "inspector": "TEST"}, headers=h, timeout=15)
        assert r.status_code == 200
        pid = r.json()["id"]

        r = requests.post(f"{API}/pmi/{pid}/complete", json={
            "inspection_date": TODAY, "result": "pass", "inspector": "TEST Inspector",
            "brake_test_type": "roller", "laden": True,
            "service_brake_pct": "68", "secondary_brake_pct": "52", "parking_brake_pct": "22",
            "notes": "TEST brake test",
        }, headers=h, timeout=15)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["brake_test_type"] == "roller"
        assert rec["laden"] is True
        assert rec["service_brake_pct"] == "68"
        assert rec["secondary_brake_pct"] == "52"
        assert rec["parking_brake_pct"] == "22"

        # Persisted in records
        r = requests.get(f"{API}/pmi/records", headers=h, timeout=15)
        got = next(x for x in r.json() if x["pmi_id"] == pid and x["inspection_date"] == TODAY)
        assert got["brake_test_type"] == "roller"
        assert got["laden"] is True

        # Cleanup
        requests.delete(f"{API}/pmi/{pid}", headers=h, timeout=15)


# ---------- Export + Reminders regression smoke ----------
class TestExportAndReminders:
    def test_export_account_returns_pdf(self, h):
        r = requests.get(f"{API}/export/account", headers=h, timeout=45)
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_export_driver_pdf(self, h):
        # Create driver then export
        r = requests.post(f"{API}/drivers", json={"name": f"TEST ExpDrv {uuid.uuid4().hex[:4]}"}, headers=h, timeout=15)
        assert r.status_code == 200
        did = r.json()["id"]
        try:
            r = requests.get(f"{API}/export/driver/{did}", headers=h, timeout=45)
            assert r.status_code == 200, r.text[:200]
            assert r.headers.get("content-type", "").startswith("application/pdf")
            assert r.content[:4] == b"%PDF"
        finally:
            requests.delete(f"{API}/drivers/{did}", headers=h, timeout=15)

    def test_reminders_settings_get_put(self, h):
        r = requests.get(f"{API}/reminders/settings", headers=h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
        # Save something back
        payload = dict(body)
        payload["enabled"] = True
        r = requests.put(f"{API}/reminders/settings", json=payload, headers=h, timeout=15)
        assert r.status_code == 200

    def test_reminders_send_smoke(self, h):
        # Endpoint should return 200 with a status (even if no email API key configured)
        r = requests.post(f"{API}/reminders/send", headers=h, timeout=45)
        # Accept 200 or 400 (missing config); as long as it's not 500
        assert r.status_code in (200, 400), r.text[:300]
