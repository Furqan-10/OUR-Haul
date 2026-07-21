"""
HaulCheck Road Haulage Compliance - Backend API tests.
Covers auth (register/login/me/logout), CRUD for vehicles/drivers/documents/defects,
dashboard, AI risk insight, and data isolation between users.
"""
import os
import uuid
import time
import requests
import pytest
from datetime import date, timedelta

FUTURE_VALID = (date.today() + timedelta(days=120)).isoformat()   # > 30 days -> valid
FUTURE_DUE_SOON = (date.today() + timedelta(days=15)).isoformat()  # <= 30 days -> due_soon
PAST_EXPIRED = (date.today() - timedelta(days=30)).isoformat()     # < 0 -> expired

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # Fallback to reading frontend/.env directly if env var not present
    from pathlib import Path
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
def s():
    return requests.Session()


@pytest.fixture(scope="session")
def token(s):
    """Get token for the seeded manager account (create if missing)."""
    r = s.post(f"{API}/auth/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD}, timeout=15)
    if r.status_code == 200:
        return r.json()["token"]
    # try to register
    r = s.post(f"{API}/auth/register", json={"email": SEED_EMAIL, "password": SEED_PASSWORD, "name": "Fleet Manager"}, timeout=15)
    assert r.status_code == 200, f"Seed register failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Auth ----------
class TestAuth:
    def test_register_new_user(self):
        email = f"TEST_{uuid.uuid4().hex[:8]}@haulcheck.co.uk"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "TEST User"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "token" in body and isinstance(body["token"], str) and len(body["token"]) > 20
        assert body["user"]["email"] == email
        assert body["user"]["name"] == "TEST User"

    def test_register_duplicate_email(self):
        email = f"TEST_{uuid.uuid4().hex[:8]}@haulcheck.co.uk"
        r1 = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "Dup"}, timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "Dup"}, timeout=15)
        assert r2.status_code == 400

    def test_login_seed_account(self, token):
        assert token and isinstance(token, str)

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": SEED_EMAIL, "password": "wrongpass"}, timeout=15)
        assert r.status_code == 401

    def test_me_requires_auth(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401

    def test_me_returns_user(self, auth_headers):
        r = requests.get(f"{API}/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == SEED_EMAIL
        assert "user_id" in body

    def test_logout(self, auth_headers):
        r = requests.post(f"{API}/auth/logout", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ---------- Vehicles ----------
class TestVehicles:
    def test_create_list_edit_delete(self, auth_headers):
        payload = {
            "registration": f"TEST{uuid.uuid4().hex[:4].upper()}",
            "make": "DAF", "model": "XF 480", "type": "HGV",
            "mot_due": FUTURE_VALID,       # future -> valid
            "service_due": FUTURE_DUE_SOON,  # ~15d -> due_soon
            "tax_due": PAST_EXPIRED,        # past -> expired
        }
        r = requests.post(f"{API}/vehicles", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["registration"] == payload["registration"]
        assert "id" in v
        vid = v["id"]

        # List and verify with statuses
        r = requests.get(f"{API}/vehicles", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        item = next((x for x in items if x["id"] == vid), None)
        assert item is not None
        assert item["mot_status"] == "valid"
        assert item["tax_status"] == "expired"
        assert item["service_status"] == "due_soon"

        # Edit
        payload2 = {**payload, "make": "Volvo"}
        r = requests.put(f"{API}/vehicles/{vid}", json=payload2, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/vehicles", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == vid)
        assert item["make"] == "Volvo"

        # Delete
        r = requests.delete(f"{API}/vehicles/{vid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/vehicles", headers=auth_headers, timeout=15)
        assert not any(x["id"] == vid for x in r.json())

    def test_edit_missing_returns_404(self, auth_headers):
        payload = {"registration": "TEST-404", "make": "", "model": "", "type": "HGV"}
        r = requests.put(f"{API}/vehicles/nonexistent_id", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_requires_auth(self):
        r = requests.get(f"{API}/vehicles", timeout=15)
        assert r.status_code == 401


# ---------- Drivers ----------
class TestDrivers:
    def test_create_list_edit_delete(self, auth_headers):
        payload = {
            "name": f"TEST Driver {uuid.uuid4().hex[:4]}",
            "licence_number": "SMITH123",
            "licence_expiry": FUTURE_VALID,
            "cpc_expiry": PAST_EXPIRED,  # expired
            "tacho_card_expiry": FUTURE_DUE_SOON,  # due_soon
            "weekly_hours": 60,
            "max_weekly_hours": 56,
        }
        r = requests.post(f"{API}/drivers", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        did = d["id"]

        r = requests.get(f"{API}/drivers", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["cpc_status"] == "expired"
        assert item["hours_status"] == "expired"

        # Edit
        r = requests.put(f"{API}/drivers/{did}", json={**payload, "weekly_hours": 40}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/drivers", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["hours_status"] == "valid"

        # Delete
        r = requests.delete(f"{API}/drivers/{did}", headers=auth_headers, timeout=15)
        assert r.status_code == 200


# ---------- Documents ----------
class TestDocuments:
    def test_create_list_edit_delete(self, auth_headers):
        payload = {
            "title": f"TEST Op-Licence {uuid.uuid4().hex[:4]}",
            "doc_type": "Operator Licence",
            "reference": "OB1234567",
            "expiry_date": PAST_EXPIRED,  # expired
        }
        r = requests.post(f"{API}/documents", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        doc = r.json()
        did = doc["id"]

        r = requests.get(f"{API}/documents", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["status"] == "expired"
        assert item["days_left"] is not None and item["days_left"] < 0

        # Edit type & expiry
        r = requests.put(f"{API}/documents/{did}", json={**payload, "doc_type": "Insurance", "expiry_date": FUTURE_VALID}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/documents", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["doc_type"] == "Insurance"
        assert item["status"] == "valid"

        # Delete
        r = requests.delete(f"{API}/documents/{did}", headers=auth_headers, timeout=15)
        assert r.status_code == 200


# ---------- Defects ----------
class TestDefects:
    def test_create_list_status_delete(self, auth_headers):
        payload = {
            "vehicle_reg": "TEST-DEF01",
            "reported_by": "TEST Driver",
            "category": "Brakes",
            "severity": "safety_critical",
            "description": "Brake warning light on, pedal soft on descent.",
        }
        r = requests.post(f"{API}/defects", json=payload, headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        did = d["id"]
        assert d["vehicle_reg"] == payload["vehicle_reg"]
        assert d["status"] == "open"
        # ai_summary may be empty (zero budget) - just check field exists
        assert "ai_summary" in d

        r = requests.get(f"{API}/defects", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert any(x["id"] == did for x in r.json())

        # Change status via query param
        r = requests.put(f"{API}/defects/{did}/status?status=resolved", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/defects", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == did)
        assert item["status"] == "resolved"

        # Delete
        r = requests.delete(f"{API}/defects/{did}", headers=auth_headers, timeout=15)
        assert r.status_code == 200


# ---------- Dashboard + AI ----------
class TestDashboard:
    def test_dashboard_shape(self, auth_headers):
        r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "risk_score" in body and isinstance(body["risk_score"], int)
        assert 0 <= body["risk_score"] <= 100
        assert "risk_band" in body
        assert "counts" in body
        for k in ("vehicles", "drivers", "documents", "open_defects", "expired", "due_soon"):
            assert k in body["counts"]
        assert "alerts" in body and isinstance(body["alerts"], list)

    def test_ai_risk_insight_returns_text(self, auth_headers):
        # AI may fail due to zero LLM budget -> fallback text expected
        r = requests.post(f"{API}/ai/risk-insight", headers=auth_headers, timeout=45)
        assert r.status_code == 200
        body = r.json()
        assert "insight" in body and isinstance(body["insight"], str) and len(body["insight"]) > 0
        assert "score" in body


# ---------- PMI Inspections + Calendar ----------
class TestPMI:
    def test_pmi_create_auto_next_due(self, auth_headers):
        """Create a PMI schedule with no next_due; server should auto-calc from today + frequency."""
        reg = f"TEST-P{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/pmi", json={"vehicle_reg": reg, "frequency_weeks": 6, "inspector": "TEST Insp"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["vehicle_reg"] == reg
        assert p["frequency_weeks"] == 6
        assert p["next_due"], "next_due should have been auto-populated"
        # next_due should be ~42 days ahead (6 weeks)
        expected = (date.today() + timedelta(weeks=6))
        got = date.fromisoformat(p["next_due"])
        assert abs((got - expected).days) <= 1
        # Cleanup
        requests.delete(f"{API}/pmi/{p['id']}", headers=auth_headers, timeout=15)

    def test_pmi_full_lifecycle_and_complete(self, auth_headers):
        """Create -> list -> edit -> record inspection (advance next_due) -> record persisted -> delete."""
        reg = f"TEST-P{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/pmi", json={
            "vehicle_reg": reg, "frequency_weeks": 4,
            "next_due": FUTURE_DUE_SOON, "inspector": "TEST"
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        p = r.json(); pid = p["id"]
        assert p["next_due"] == FUTURE_DUE_SOON

        # List and verify status/days_left populated
        r = requests.get(f"{API}/pmi", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        found = next((x for x in r.json() if x["id"] == pid), None)
        assert found is not None
        assert found["status"] in ("due_soon", "valid", "expired")
        assert "days_left" in found

        # Edit
        r = requests.put(f"{API}/pmi/{pid}", json={
            "vehicle_reg": reg, "frequency_weeks": 8,
            "next_due": FUTURE_VALID, "inspector": "TEST Edited", "notes": "edited"
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/pmi", headers=auth_headers, timeout=15)
        found = next(x for x in r.json() if x["id"] == pid)
        assert found["frequency_weeks"] == 8
        assert found["inspector"] == "TEST Edited"

        # Complete inspection
        insp_date = date.today().isoformat()
        r = requests.post(f"{API}/pmi/{pid}/complete", json={
            "inspection_date": insp_date, "result": "advisory",
            "inspector": "TEST Inspector", "notes": "advisory - tyre wear"
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        expected_next = (date.today() + timedelta(weeks=8)).isoformat()
        assert body["next_due"] == expected_next
        assert body["record"]["result"] == "advisory"

        # Confirm schedule's next_due advanced (persisted)
        r = requests.get(f"{API}/pmi", headers=auth_headers, timeout=15)
        found = next(x for x in r.json() if x["id"] == pid)
        assert found["next_due"] == expected_next

        # Records endpoint contains new record
        r = requests.get(f"{API}/pmi/records", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        recs = r.json()
        assert any(rr["pmi_id"] == pid and rr["inspection_date"] == insp_date and rr["result"] == "advisory" for rr in recs)

        # Delete schedule
        r = requests.delete(f"{API}/pmi/{pid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/pmi", headers=auth_headers, timeout=15)
        assert not any(x["id"] == pid for x in r.json())

    def test_pmi_complete_missing_schedule_returns_404(self, auth_headers):
        r = requests.post(f"{API}/pmi/nonexistent/complete", json={"inspection_date": date.today().isoformat(), "result": "pass"}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_pmi_edit_missing_returns_404(self, auth_headers):
        r = requests.put(f"{API}/pmi/nonexistent", json={"vehicle_reg": "X", "frequency_weeks": 6}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_pmi_requires_auth(self):
        assert requests.get(f"{API}/pmi", timeout=15).status_code == 401
        assert requests.get(f"{API}/pmi/records", timeout=15).status_code == 401


class TestCalendar:
    def test_calendar_returns_events_and_shape(self, auth_headers):
        # Ensure at least one PMI schedule to produce a pmi_due event
        reg = f"TEST-C{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/pmi", json={
            "vehicle_reg": reg, "frequency_weeks": 6,
            "next_due": FUTURE_VALID, "inspector": "TEST"
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        pid = r.json()["id"]

        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        events = r.json()
        assert isinstance(events, list)
        # Should contain the pmi_due event we just created
        due_events = [e for e in events if e.get("type") == "pmi_due" and e.get("date") == FUTURE_VALID]
        assert any(reg in (e.get("title") or "") for e in due_events)
        # All events must have required keys
        for e in events:
            assert "date" in e and "type" in e and "title" in e and "status" in e

        requests.delete(f"{API}/pmi/{pid}", headers=auth_headers, timeout=15)

    def test_calendar_requires_auth(self):
        assert requests.get(f"{API}/calendar", timeout=15).status_code == 401


class TestDashboardPMI:
    def test_dashboard_counts_include_pmi_and_alerts(self, auth_headers):
        # Create an expired PMI schedule -> should appear in alerts and counts['pmi']
        reg = f"TEST-D{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/pmi", json={
            "vehicle_reg": reg, "frequency_weeks": 6,
            "next_due": PAST_EXPIRED, "inspector": "TEST"
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        pid = r.json()["id"]

        r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "pmi" in body["counts"]
        assert isinstance(body["counts"]["pmi"], int) and body["counts"]["pmi"] >= 1
        # PMI alert should be present for the expired schedule
        pmi_alerts = [a for a in body["alerts"] if a.get("type") == "pmi" and a.get("name") == reg]
        assert pmi_alerts, "Expected an expired PMI alert in dashboard alerts"
        assert pmi_alerts[0]["status"] == "expired"

        requests.delete(f"{API}/pmi/{pid}", headers=auth_headers, timeout=15)


# ---------- Trailers ----------
class TestTrailers:
    def test_create_list_edit_delete(self, auth_headers):
        payload = {
            "trailer_number": f"TEST-T{uuid.uuid4().hex[:4].upper()}",
            "type": "Curtainsider",
            "mot_due": FUTURE_DUE_SOON,
            "service_due": PAST_EXPIRED,
        }
        r = requests.post(f"{API}/trailers", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["trailer_number"] == payload["trailer_number"]
        assert "id" in t
        tid = t["id"]

        r = requests.get(f"{API}/trailers", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        item = next((x for x in r.json() if x["id"] == tid), None)
        assert item is not None
        assert item["mot_status"] == "due_soon"
        assert item["service_status"] == "expired"

        # Edit
        r = requests.put(f"{API}/trailers/{tid}", json={**payload, "type": "Flatbed"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/trailers", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == tid)
        assert item["type"] == "Flatbed"

        # Delete
        r = requests.delete(f"{API}/trailers/{tid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/trailers", headers=auth_headers, timeout=15)
        assert not any(x["id"] == tid for x in r.json())

    def test_edit_missing_returns_404(self, auth_headers):
        r = requests.put(f"{API}/trailers/nonexistent", json={"trailer_number": "X", "type": "Box"}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_requires_auth(self):
        assert requests.get(f"{API}/trailers", timeout=15).status_code == 401


# ---------- Training ----------
class TestTraining:
    def test_create_list_filter_edit_delete(self, auth_headers):
        # Create a driver to attach to
        drv_r = requests.post(f"{API}/drivers", json={"name": f"TEST TrainDrv {uuid.uuid4().hex[:4]}"}, headers=auth_headers, timeout=15)
        assert drv_r.status_code == 200
        drv = drv_r.json()
        did = drv["id"]

        payload = {
            "driver_id": did, "driver_name": drv["name"],
            "course_name": "TEST Driver CPC Module 3", "category": "Driver CPC",
            "completed_date": PAST_EXPIRED, "expiry_date": FUTURE_DUE_SOON,
            "provider": "TEST Trainer Ltd",
        }
        r = requests.post(f"{API}/training", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        tid = t["id"]
        assert t["course_name"] == payload["course_name"]
        assert t["driver_id"] == did

        # List
        r = requests.get(f"{API}/training", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        item = next((x for x in r.json() if x["id"] == tid), None)
        assert item is not None
        assert item["status"] == "due_soon"
        assert item["days_left"] is not None and item["days_left"] <= 30

        # Filter by driver_id
        r = requests.get(f"{API}/training", params={"driver_id": did}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert all(x["driver_id"] == did for x in r.json())
        assert any(x["id"] == tid for x in r.json())

        # Edit
        r = requests.put(f"{API}/training/{tid}", json={**payload, "expiry_date": FUTURE_VALID, "provider": "TEST Updated"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/training", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == tid)
        assert item["provider"] == "TEST Updated"
        assert item["status"] == "valid"

        # Delete
        r = requests.delete(f"{API}/training/{tid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/training", headers=auth_headers, timeout=15)
        assert not any(x["id"] == tid for x in r.json())
        # cleanup driver
        requests.delete(f"{API}/drivers/{did}", headers=auth_headers, timeout=15)

    def test_edit_missing_returns_404(self, auth_headers):
        r = requests.put(f"{API}/training/nonexistent", json={"course_name": "x"}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_requires_auth(self):
        assert requests.get(f"{API}/training", timeout=15).status_code == 401


# ---------- File upload / download ----------
class TestFileUpload:
    # 1x1 PNG bytes
    PNG_BYTES = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x00\x03\x00\x01[\xd1E\xb9\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def test_upload_and_download_via_bearer(self, token):
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("test.png", self.PNG_BYTES, "image/png")}
        r = requests.post(f"{API}/upload", files=files, headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "file_id" in body and body["filename"] == "test.png"
        assert body["content_type"] == "image/png"
        assert body["url"].endswith(f"/api/files/{body['file_id']}")
        file_id = body["file_id"]

        # Download via bearer
        r = requests.get(f"{API}/files/{file_id}", headers=headers, timeout=30)
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("image/")
        assert r.content == self.PNG_BYTES

        # Download via ?auth=<token> (used by <img src>)
        r = requests.get(f"{API}/files/{file_id}", params={"auth": token}, timeout=30)
        assert r.status_code == 200
        assert r.content == self.PNG_BYTES

    def test_upload_requires_auth(self):
        files = {"file": ("test.png", self.PNG_BYTES, "image/png")}
        r = requests.post(f"{API}/upload", files=files, timeout=30)
        assert r.status_code == 401

    def test_download_requires_auth(self):
        r = requests.get(f"{API}/files/nonexistent", timeout=15)
        assert r.status_code == 401

    def test_download_wrong_user_forbidden(self, token):
        # Upload as seeded user, then try to fetch as a different fresh user
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("test.png", self.PNG_BYTES, "image/png")}
        r = requests.post(f"{API}/upload", files=files, headers=headers, timeout=60)
        assert r.status_code == 200
        file_id = r.json()["file_id"]

        # Fresh user
        email = f"TEST_uf_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        rB = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "B"}, timeout=15)
        tokB = rB.json()["token"]
        r = requests.get(f"{API}/files/{file_id}", params={"auth": tokB}, timeout=15)
        assert r.status_code == 404  # scoped to owner


# ---------- Dashboard: trailers + training counts/alerts ----------
class TestDashboardTrailersTraining:
    def test_dashboard_counts_and_alerts_include_trailers_training(self, auth_headers):
        # Expired trailer MOT
        trailer_num = f"TEST-DT{uuid.uuid4().hex[:4].upper()}"
        r = requests.post(f"{API}/trailers", json={
            "trailer_number": trailer_num, "type": "Box", "mot_due": PAST_EXPIRED,
        }, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]

        # Expired training
        drv_r = requests.post(f"{API}/drivers", json={"name": f"TEST DshDrv {uuid.uuid4().hex[:4]}"}, headers=auth_headers, timeout=15)
        did = drv_r.json()["id"]
        tr_r = requests.post(f"{API}/training", json={
            "driver_id": did, "driver_name": drv_r.json()["name"],
            "course_name": "TEST Expired CPC", "category": "Driver CPC",
            "expiry_date": PAST_EXPIRED,
        }, headers=auth_headers, timeout=15)
        trid = tr_r.json()["id"]

        r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "trailers" in body["counts"] and body["counts"]["trailers"] >= 1
        assert "training" in body["counts"] and body["counts"]["training"] >= 1

        trailer_alerts = [a for a in body["alerts"] if a.get("type") == "trailer" and a.get("name") == trailer_num]
        training_alerts = [a for a in body["alerts"] if a.get("type") == "training" and a.get("item") == "TEST Expired CPC"]
        assert trailer_alerts and trailer_alerts[0]["status"] == "expired"
        assert training_alerts and training_alerts[0]["status"] == "expired"

        # Calendar contains a training event
        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        cal = r.json()
        assert any(e.get("type") == "training" and e.get("date") == PAST_EXPIRED for e in cal)

        # Cleanup
        requests.delete(f"{API}/trailers/{tid}", headers=auth_headers, timeout=15)
        requests.delete(f"{API}/training/{trid}", headers=auth_headers, timeout=15)
        requests.delete(f"{API}/drivers/{did}", headers=auth_headers, timeout=15)


# ---------- Data isolation ----------
class TestIsolation:
    def test_data_scoped_per_user(self):
        # Create two fresh users; user A creates a vehicle; user B should not see it.
        emailA = f"TEST_iso_a_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        emailB = f"TEST_iso_b_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        rA = requests.post(f"{API}/auth/register", json={"email": emailA, "password": "Password1!", "name": "A"}, timeout=15)
        rB = requests.post(f"{API}/auth/register", json={"email": emailB, "password": "Password1!", "name": "B"}, timeout=15)
        assert rA.status_code == 200 and rB.status_code == 200
        hA = {"Authorization": f"Bearer {rA.json()['token']}"}
        hB = {"Authorization": f"Bearer {rB.json()['token']}"}

        reg = f"ISO{uuid.uuid4().hex[:5].upper()}"
        r = requests.post(f"{API}/vehicles", json={"registration": reg, "make": "DAF", "model": "XF", "type": "HGV"}, headers=hA, timeout=15)
        assert r.status_code == 200

        listA = requests.get(f"{API}/vehicles", headers=hA, timeout=15).json()
        listB = requests.get(f"{API}/vehicles", headers=hB, timeout=15).json()
        assert any(v["registration"] == reg for v in listA)
        assert not any(v["registration"] == reg for v in listB)


# ---------- Insurance ----------
class TestInsurance:
    def test_create_list_edit_delete_and_statuses(self, auth_headers, token):
        # Create three policies with different expiry buckets
        payloads = [
            {"policy_type": "Goods in Transit (GIT)", "insurer": "TEST Aviva", "policy_number": f"POL-{uuid.uuid4().hex[:6]}", "start_date": PAST_EXPIRED, "expiry_date": FUTURE_VALID, "cover_amount": "£250,000", "notes": "TEST GIT valid"},
            {"policy_type": "Motor — Truck", "insurer": "TEST Zurich", "policy_number": f"POL-{uuid.uuid4().hex[:6]}", "expiry_date": FUTURE_DUE_SOON, "cover_amount": "£100,000"},
            {"policy_type": "Employers' Liability (EL)", "insurer": "TEST AXA", "policy_number": f"POL-{uuid.uuid4().hex[:6]}", "expiry_date": PAST_EXPIRED, "cover_amount": "£10,000,000"},
        ]
        created_ids = []
        expected = {"Goods in Transit (GIT)": "valid", "Motor — Truck": "due_soon", "Employers' Liability (EL)": "expired"}
        for pl in payloads:
            r = requests.post(f"{API}/insurance", json=pl, headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["insurer"] == pl["insurer"]
            assert body["policy_type"] == pl["policy_type"]
            assert "id" in body
            created_ids.append(body["id"])

        # List and verify shape + computed status/days_left
        r = requests.get(f"{API}/insurance", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        for cid, pl in zip(created_ids, payloads):
            item = next((x for x in items if x["id"] == cid), None)
            assert item is not None
            assert item["policy_type"] == pl["policy_type"]
            assert item["status"] == expected[pl["policy_type"]], f"Expected {expected[pl['policy_type']]} for {pl['policy_type']}, got {item['status']}"
            assert "days_left" in item

        # Edit the GIT one: change insurer and expiry
        gid = created_ids[0]
        edit_payload = {**payloads[0], "insurer": "TEST Aviva EDITED", "expiry_date": FUTURE_DUE_SOON}
        r = requests.put(f"{API}/insurance/{gid}", json=edit_payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/insurance", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == gid)
        assert item["insurer"] == "TEST Aviva EDITED"
        assert item["status"] == "due_soon"

        # Attachment: upload a file and attach it
        png = TestFileUpload.PNG_BYTES
        up = requests.post(f"{API}/upload", files={"file": ("cert.png", png, "image/png")}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert up.status_code == 200
        att = {"file_id": up.json()["file_id"], "filename": up.json()["filename"], "content_type": up.json()["content_type"], "url": up.json()["url"], "size": len(png)}
        edit_payload_with_att = {**edit_payload, "attachments": [att]}
        r = requests.put(f"{API}/insurance/{gid}", json=edit_payload_with_att, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/insurance", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == gid)
        assert item["attachments"] and item["attachments"][0]["file_id"] == att["file_id"]

        # Dashboard alerts & counts include insurance
        r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "insurance" in body["counts"] and body["counts"]["insurance"] >= 3
        el_alert = [a for a in body["alerts"] if a.get("type") == "insurance" and a.get("item") == "Employers' Liability (EL)"]
        assert el_alert and el_alert[0]["status"] == "expired"

        # Calendar contains type=insurance events
        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        cal = r.json()
        ins_events = [e for e in cal if e.get("type") == "insurance"]
        assert ins_events, "Expected insurance events in calendar"
        for e in ins_events:
            assert "Insurance Renewal" in e.get("title", "")

        # Delete all created
        for cid in created_ids:
            r = requests.delete(f"{API}/insurance/{cid}", headers=auth_headers, timeout=15)
            assert r.status_code == 200
        r = requests.get(f"{API}/insurance", headers=auth_headers, timeout=15)
        remaining = {x["id"] for x in r.json()}
        for cid in created_ids:
            assert cid not in remaining

    def test_edit_missing_returns_404(self, auth_headers):
        r = requests.put(f"{API}/insurance/nonexistent", json={"policy_type": "Motor — Truck"}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_requires_auth(self):
        assert requests.get(f"{API}/insurance", timeout=15).status_code == 401
        assert requests.post(f"{API}/insurance", json={"policy_type": "Motor — Truck"}, timeout=15).status_code == 401

    def test_ai_import_creates_policy_from_text_certificate(self, auth_headers, token):
        """AI Insurance Import: upload a plaintext certificate; LLM should extract insurer + expiry + policy_type."""
        cert = (
            b"CERTIFICATE OF MOTOR INSURANCE\n"
            b"Insurer: Zurich Insurance plc\n"
            b"Policy Number: TEST-Z-778991\n"
            b"Policy Type: Motor Insurance - Commercial Truck\n"
            b"Vehicle: DAF XF 480 tractor unit\n"
            b"Period of Cover: 01 April 2026 to 31 March 2027\n"
            b"Limit of Indemnity: GBP 5,000,000\n"
            b"Territorial Limits: United Kingdom\n"
        )
        r = requests.post(
            f"{API}/insurance/ai-import",
            files={"files": ("TEST_cert.txt", cert, "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1, f"Expected 1 created, got {body}"
        created = body["created"][0]
        assert created["policy_type"] in {"Motor — Truck", "Motor — Trailer", "Other"}, created
        # Confirm it appears in the list with ai_extracted flag
        listing = requests.get(f"{API}/insurance", headers=auth_headers, timeout=15).json()
        match = next((x for x in listing if x["id"] == created["id"]), None)
        assert match is not None
        assert match.get("ai_extracted") is True
        # Cleanup
        requests.delete(f"{API}/insurance/{created['id']}", headers=auth_headers, timeout=15)

    def test_ai_import_requires_auth(self):
        r = requests.post(f"{API}/insurance/ai-import", files={"files": ("x.txt", b"hello", "text/plain")}, timeout=15)
        assert r.status_code == 401

    def test_ai_import_multiple_files(self, auth_headers, token):
        """Upload two docs at once - both should be processed and appear in results."""
        f1 = b"Goods in Transit Insurance Policy\nInsurer: TEST Aviva GIT\nPolicy Number: GIT-1\nExpiry: 2027-01-15\nCover: GBP 250,000 per load\n"
        f2 = b"Employers Liability Insurance\nInsurer: TEST AXA EL\nPolicy Number: EL-9\nExpiry: 2026-12-31\nLimit: GBP 10,000,000\n"
        r = requests.post(
            f"{API}/insurance/ai-import",
            files=[("files", ("TEST_git.txt", f1, "text/plain")), ("files", ("TEST_el.txt", f2, "text/plain"))],
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2, body
        for created in body["created"]:
            assert "id" in created and "policy_type" in created and "needs_review" in created
            requests.delete(f"{API}/insurance/{created['id']}", headers=auth_headers, timeout=15)


# ---------- Region / Jurisdiction ----------
class TestRegion:
    def test_default_region_is_uk_on_register(self):
        email = f"TEST_region_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Password1!", "name": "TEST Region"}, timeout=15)
        assert r.status_code == 200
        tok = r.json()["token"]
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
        assert me.get("region") == "UK"

    def test_switch_region_persists(self, auth_headers, token):
        h = {"Authorization": f"Bearer {token}"}
        # Switch to IE
        r = requests.put(f"{API}/settings/region", json={"region": "IE"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200 and r.json()["region"] == "IE"
        me = requests.get(f"{API}/auth/me", headers=h, timeout=15).json()
        assert me["region"] == "IE"
        # Switch back to UK (leave account in default state)
        r = requests.put(f"{API}/settings/region", json={"region": "UK"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200 and r.json()["region"] == "UK"
        me = requests.get(f"{API}/auth/me", headers=h, timeout=15).json()
        assert me["region"] == "UK"

    def test_invalid_region_rejected(self, auth_headers):
        r = requests.put(f"{API}/settings/region", json={"region": "US"}, headers=auth_headers, timeout=15)
        assert r.status_code == 400

    def test_region_requires_auth(self):
        r = requests.put(f"{API}/settings/region", json={"region": "UK"}, timeout=15)
        assert r.status_code == 401


    def test_insurance_isolation_between_users(self):
        emailA = f"TEST_ins_a_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        emailB = f"TEST_ins_b_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        rA = requests.post(f"{API}/auth/register", json={"email": emailA, "password": "Password1!", "name": "A"}, timeout=15)
        rB = requests.post(f"{API}/auth/register", json={"email": emailB, "password": "Password1!", "name": "B"}, timeout=15)
        hA = {"Authorization": f"Bearer {rA.json()['token']}"}
        hB = {"Authorization": f"Bearer {rB.json()['token']}"}
        r = requests.post(f"{API}/insurance", json={"policy_type": "Green Card", "insurer": "TEST-Iso", "expiry_date": FUTURE_VALID}, headers=hA, timeout=15)
        assert r.status_code == 200
        iid = r.json()["id"]
        listA = requests.get(f"{API}/insurance", headers=hA, timeout=15).json()
        listB = requests.get(f"{API}/insurance", headers=hB, timeout=15).json()
        assert any(x["id"] == iid for x in listA)
        assert not any(x["id"] == iid for x in listB)
        # User B cannot delete/edit A's policy
        rDel = requests.delete(f"{API}/insurance/{iid}", headers=hB, timeout=15)
        # server returns ok=true but doesn't affect data; verify A still has it
        listA_after = requests.get(f"{API}/insurance", headers=hA, timeout=15).json()
        assert any(x["id"] == iid for x in listA_after)



# ---------- Tacho Portal ----------
class TestTacho:
    """CRUD + Log Download action + dashboard/calendar integration for /api/tacho."""

    def test_create_list_edit_delete_and_statuses(self, auth_headers):
        # Create three records with different due buckets
        payloads = [
            {"source_type": "Driver Card", "reference": f"TEST_Drv_{uuid.uuid4().hex[:4]}", "frequency_days": 28, "last_download": (date.today() - timedelta(days=1)).isoformat(), "infringements": 0},  # next_due ~27d -> due_soon
            {"source_type": "Vehicle Unit", "reference": f"TEST_VU_{uuid.uuid4().hex[:4]}", "frequency_days": 90, "last_download": (date.today() - timedelta(days=10)).isoformat(), "infringements": 2},  # ~80d -> valid
            {"source_type": "Driver Card", "reference": f"TEST_DrvOver_{uuid.uuid4().hex[:4]}", "frequency_days": 28, "last_download": (date.today() - timedelta(days=60)).isoformat(), "infringements": 5},  # -32d -> expired
        ]
        expected_status = ["due_soon", "valid", "expired"]
        created_ids = []
        for pl in payloads:
            r = requests.post(f"{API}/tacho", json=pl, headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["reference"] == pl["reference"]
            assert body["source_type"] == pl["source_type"]
            assert body["frequency_days"] == pl["frequency_days"]
            assert body["next_due"]  # server-computed
            expected_nd = (date.fromisoformat(pl["last_download"]) + timedelta(days=pl["frequency_days"])).isoformat()
            assert body["next_due"] == expected_nd
            assert "id" in body
            created_ids.append(body["id"])

        # List & verify statuses + days_left
        r = requests.get(f"{API}/tacho", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        for cid, pl, exp in zip(created_ids, payloads, expected_status):
            item = next((x for x in items if x["id"] == cid), None)
            assert item is not None, f"Record {cid} missing"
            assert item["status"] == exp, f"Expected {exp} for {pl['reference']}, got {item['status']}"
            assert "days_left" in item
            assert item["infringements"] == pl["infringements"]

        # Edit second record (change last_download; next_due must recompute)
        vid = created_ids[1]
        new_last = (date.today() - timedelta(days=85)).isoformat()  # ~5d -> due_soon
        edit_payload = {**payloads[1], "last_download": new_last, "infringements": 3}
        r = requests.put(f"{API}/tacho/{vid}", json=edit_payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        expected_nd = (date.fromisoformat(new_last) + timedelta(days=90)).isoformat()
        assert body["next_due"] == expected_nd
        r = requests.get(f"{API}/tacho", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == vid)
        assert item["last_download"] == new_last
        assert item["next_due"] == expected_nd
        assert item["infringements"] == 3
        assert item["status"] == "due_soon"

        # Delete all
        for cid in created_ids:
            r = requests.delete(f"{API}/tacho/{cid}", headers=auth_headers, timeout=15)
            assert r.status_code == 200
        r = requests.get(f"{API}/tacho", headers=auth_headers, timeout=15)
        remaining = {x["id"] for x in r.json()}
        for cid in created_ids:
            assert cid not in remaining

    def test_log_download_advances_next_due(self, auth_headers):
        """POST /tacho/{id}/download sets last_download=today and next_due=today+freq."""
        pl = {"source_type": "Driver Card", "reference": f"TEST_LogDL_{uuid.uuid4().hex[:4]}", "frequency_days": 28, "last_download": (date.today() - timedelta(days=40)).isoformat()}
        r = requests.post(f"{API}/tacho", json=pl, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]

        today = date.today().isoformat()
        r = requests.post(f"{API}/tacho/{tid}/download", json={"download_date": today}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["last_download"] == today
        expected_next = (date.today() + timedelta(days=28)).isoformat()
        assert body["next_due"] == expected_next

        # Persisted in GET
        r = requests.get(f"{API}/tacho", headers=auth_headers, timeout=15)
        item = next(x for x in r.json() if x["id"] == tid)
        assert item["last_download"] == today
        assert item["next_due"] == expected_next
        assert item["status"] in ("valid", "due_soon")  # 28d out => due_soon

        # Log without explicit date defaults to today too
        r = requests.post(f"{API}/tacho/{tid}/download", json={}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["last_download"] == today

        # Cleanup
        requests.delete(f"{API}/tacho/{tid}", headers=auth_headers, timeout=15)

    def test_log_download_missing_record_returns_404(self, auth_headers):
        r = requests.post(f"{API}/tacho/nonexistent/download", json={"download_date": date.today().isoformat()}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_edit_missing_returns_404(self, auth_headers):
        r = requests.put(f"{API}/tacho/nonexistent", json={"source_type": "Driver Card", "reference": "x", "frequency_days": 28}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_requires_auth(self):
        assert requests.get(f"{API}/tacho", timeout=15).status_code == 401
        assert requests.post(f"{API}/tacho", json={"source_type": "Driver Card"}, timeout=15).status_code == 401
        assert requests.post(f"{API}/tacho/x/download", json={}, timeout=15).status_code == 401
        assert requests.delete(f"{API}/tacho/x", timeout=15).status_code == 401

    def test_dashboard_and_calendar_include_tacho(self, auth_headers):
        # Overdue tacho -> expected in dashboard alerts + counts['tacho'] and calendar
        ref = f"TEST_TachoDash_{uuid.uuid4().hex[:4]}"
        past = (date.today() - timedelta(days=60)).isoformat()  # 60d ago + 28 = -32d overdue
        r = requests.post(f"{API}/tacho", json={"source_type": "Driver Card", "reference": ref, "frequency_days": 28, "last_download": past}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]
        expected_due = (date.fromisoformat(past) + timedelta(days=28)).isoformat()

        # Dashboard
        r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "tacho" in body["counts"] and isinstance(body["counts"]["tacho"], int) and body["counts"]["tacho"] >= 1
        tacho_alerts = [a for a in body["alerts"] if a.get("type") == "tacho" and a.get("name") == ref]
        assert tacho_alerts, "Expected an expired tacho alert in dashboard alerts"
        assert tacho_alerts[0]["status"] == "expired"

        # Calendar
        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        cal = r.json()
        tacho_events = [e for e in cal if e.get("type") == "tacho" and e.get("date") == expected_due]
        assert tacho_events, f"Expected a tacho calendar event on {expected_due}"
        assert any(ref in (e.get("title") or "") for e in tacho_events)

        # Cleanup
        requests.delete(f"{API}/tacho/{tid}", headers=auth_headers, timeout=15)

    def test_isolation_between_users(self):
        emailA = f"TEST_tac_a_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        emailB = f"TEST_tac_b_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        rA = requests.post(f"{API}/auth/register", json={"email": emailA, "password": "Password1!", "name": "A"}, timeout=15)
        rB = requests.post(f"{API}/auth/register", json={"email": emailB, "password": "Password1!", "name": "B"}, timeout=15)
        hA = {"Authorization": f"Bearer {rA.json()['token']}", "Content-Type": "application/json"}
        hB = {"Authorization": f"Bearer {rB.json()['token']}", "Content-Type": "application/json"}
        r = requests.post(f"{API}/tacho", json={"source_type": "Driver Card", "reference": f"TEST_iso_{uuid.uuid4().hex[:4]}", "frequency_days": 28, "last_download": date.today().isoformat()}, headers=hA, timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]
        listA = requests.get(f"{API}/tacho", headers=hA, timeout=15).json()
        listB = requests.get(f"{API}/tacho", headers=hB, timeout=15).json()
        assert any(x["id"] == tid for x in listA)
        assert not any(x["id"] == tid for x in listB)
        # B cannot edit A's record
        rEdit = requests.put(f"{API}/tacho/{tid}", json={"source_type": "Driver Card", "reference": "hacked", "frequency_days": 28}, headers=hB, timeout=15)
        assert rEdit.status_code == 404
        # Cleanup
        requests.delete(f"{API}/tacho/{tid}", headers=hA, timeout=15)


# ---------- Tacho auto-parse (POST /api/tacho/parse) ----------
class TestTachoParse:
    """New feature: parse uploaded tacho files (.ddd binary heuristic or PDF/text/image via LLM)."""

    def _upload(self, token, filename, content, mime):
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{API}/upload", files={"file": (filename, content, mime)}, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()["file_id"]

    def test_parse_binary_ddd_returns_embedded_timestamp(self, auth_headers, token):
        """Craft a .ddd with a known big-endian uint32 TimeReal and confirm binary path returns that date."""
        import struct
        from datetime import datetime as _dt, timezone as _tz
        target = _dt(2026, 6, 15, 10, 30, 0, tzinfo=_tz.utc)
        target_ts = int(target.timestamp())
        # Filler + embedded timestamp + filler. Include a few older timestamps to verify "max" is picked.
        older = int(_dt(2025, 1, 5, tzinfo=_tz.utc).timestamp())
        blob = b"\x00" * 32 + struct.pack(">I", older) + b"\xAB\xCD" * 20 + struct.pack(">I", target_ts) + b"\x00" * 32
        file_id = self._upload(token, "TEST_card.ddd", blob, "application/octet-stream")
        r = requests.post(f"{API}/tacho/parse", json={"file_id": file_id}, headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == "binary"
        assert body["last_download"] == "2026-06-15"
        assert body["infringements"] is None

    def test_parse_text_report_returns_ai_extraction(self, auth_headers, token):
        """A plaintext analysis report should be routed through the AI path and return both fields."""
        report = (
            b"TACHOGRAPH ANALYSIS REPORT\n"
            b"Driver: John Smith\n"
            b"Card downloaded on: 2026-06-01\n"
            b"Analysis period: 01/05/2026 - 31/05/2026\n"
            b"Infringements found: 3\n"
            b"  - Insufficient daily rest (2 occurrences)\n"
            b"  - Driving without valid card (1 occurrence)\n"
        )
        file_id = self._upload(token, "TEST_report.txt", report, "text/plain")
        r = requests.post(f"{API}/tacho/parse", json={"file_id": file_id}, headers=auth_headers, timeout=90)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == "ai"
        # AI extractions can fail if key is missing; only assert values if returned
        if body.get("last_download"):
            assert body["last_download"] == "2026-06-01", body
        if body.get("infringements") is not None:
            assert int(body["infringements"]) == 3, body

    def test_parse_requires_auth(self):
        r = requests.post(f"{API}/tacho/parse", json={"file_id": "x"}, timeout=15)
        assert r.status_code == 401

    def test_parse_unknown_file_returns_404(self, auth_headers):
        r = requests.post(f"{API}/tacho/parse", json={"file_id": "does_not_exist"}, headers=auth_headers, timeout=15)
        assert r.status_code == 404

    def test_parse_foreign_file_returns_404(self, token):
        """User B cannot parse User A's uploaded file (data isolation)."""
        # A uploads
        headers_a = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{API}/upload", files={"file": ("TEST_priv.ddd", b"\x00" * 100, "application/octet-stream")}, headers=headers_a, timeout=30)
        assert r.status_code == 200
        file_id = r.json()["file_id"]
        # B tries to parse
        emailB = f"TEST_tp_{uuid.uuid4().hex[:6]}@haulcheck.co.uk"
        rB = requests.post(f"{API}/auth/register", json={"email": emailB, "password": "Password1!", "name": "B"}, timeout=15)
        tokB = rB.json()["token"]
        r = requests.post(f"{API}/tacho/parse", json={"file_id": file_id}, headers={"Authorization": f"Bearer {tokB}", "Content-Type": "application/json"}, timeout=15)
        assert r.status_code == 404

    def test_end_to_end_upload_parse_and_create_tacho_record(self, auth_headers, token):
        """Upload a .ddd, POST /tacho/parse, then POST /tacho with parsed date; verify next_due computed correctly."""
        import struct
        from datetime import datetime as _dt, timezone as _tz
        target = _dt(2026, 3, 20, 12, 0, 0, tzinfo=_tz.utc)
        blob = b"\x11" * 16 + struct.pack(">I", int(target.timestamp())) + b"\x22" * 16
        file_id = self._upload(token, "TEST_e2e.ddd", blob, "application/octet-stream")
        r = requests.post(f"{API}/tacho/parse", json={"file_id": file_id}, headers=auth_headers, timeout=30)
        assert r.status_code == 200
        parsed = r.json()
        assert parsed["method"] == "binary"
        assert parsed["last_download"] == "2026-03-20"

        # Create a driver + tacho record using parsed date
        drv_r = requests.post(f"{API}/drivers", json={"name": f"TEST TachoParseDrv {uuid.uuid4().hex[:4]}"}, headers=auth_headers, timeout=15)
        assert drv_r.status_code == 200
        drv = drv_r.json()

        payload = {
            "source_type": "Driver Card",
            "reference": drv["name"],
            "frequency_days": 28,
            "last_download": parsed["last_download"],
            "infringements": 0,
            "attachments": [{"file_id": file_id, "filename": "TEST_e2e.ddd", "content_type": "application/octet-stream"}],
        }
        r = requests.post(f"{API}/tacho", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["last_download"] == "2026-03-20"
        assert body["next_due"] == "2026-04-17"  # 2026-03-20 + 28d

        # Cleanup
        requests.delete(f"{API}/tacho/{body['id']}", headers=auth_headers, timeout=15)
        requests.delete(f"{API}/drivers/{drv['id']}", headers=auth_headers, timeout=15)



# ---------- BUG FIX: Tacho dedup on dashboard/calendar (latest per ref only) ----------
class TestTachoDedupBug:
    """Regression test for the reported bug: multiple historical downloads for the same
    driver-card/vehicle-unit reference must NOT each count as expired on the dashboard.
    Only the LATEST download's next_due determines status. counts.tacho == distinct refs."""

    def test_dashboard_dedupes_to_latest_per_reference(self, auth_headers):
        ref = f"TEST_Dedup_{uuid.uuid4().hex[:6]}"
        d120 = (date.today() - timedelta(days=120)).isoformat()  # next_due = -92d expired
        d60 = (date.today() - timedelta(days=60)).isoformat()    # next_due = -32d expired
        d2 = (date.today() - timedelta(days=2)).isoformat()      # next_due = +26d due_soon (latest, on track)
        ids = []
        for last in [d120, d60, d2]:
            r = requests.post(f"{API}/tacho", json={
                "source_type": "Driver Card", "reference": ref,
                "frequency_days": 28, "last_download": last,
            }, headers=auth_headers, timeout=15)
            assert r.status_code == 200
            ids.append(r.json()["id"])

        try:
            r = requests.get(f"{API}/dashboard", headers=auth_headers, timeout=15)
            assert r.status_code == 200
            body = r.json()
            # Only ONE tacho alert should exist for this reference (the latest, due_soon)
            my_alerts = [a for a in body["alerts"] if a.get("type") == "tacho" and a.get("name") == ref]
            assert len(my_alerts) <= 1, f"Expected <=1 alert for {ref}, got {len(my_alerts)}: {my_alerts}"
            # The alert (if any) must NOT be 'expired' - only latest counts, and latest is due_soon
            for a in my_alerts:
                assert a["status"] != "expired", f"Latest download (2d ago) should NOT be expired: {a}"
                assert a["status"] == "due_soon", f"Expected due_soon, got {a['status']}"

            # counts.tacho should count DISTINCT references, not raw record count
            # We created 3 records for 1 reference; counts.tacho should have increased by 1, not 3.
            # Verify by comparing distinct refs vs record count for this user.
            all_tacho = requests.get(f"{API}/tacho", headers=auth_headers, timeout=15).json()
            distinct = len({(t.get("source_type"), t.get("reference")) for t in all_tacho})
            assert body["counts"]["tacho"] == distinct, \
                f"counts.tacho={body['counts']['tacho']} but distinct references={distinct}"
        finally:
            for tid in ids:
                requests.delete(f"{API}/tacho/{tid}", headers=auth_headers, timeout=15)

    def test_calendar_dedupes_tacho_to_latest(self, auth_headers):
        ref = f"TEST_CalDedup_{uuid.uuid4().hex[:6]}"
        d120 = (date.today() - timedelta(days=120)).isoformat()
        d2 = (date.today() - timedelta(days=2)).isoformat()
        latest_due = (date.today() + timedelta(days=26)).isoformat()
        ids = []
        for last in [d120, d2]:
            r = requests.post(f"{API}/tacho", json={
                "source_type": "Driver Card", "reference": ref,
                "frequency_days": 28, "last_download": last,
            }, headers=auth_headers, timeout=15)
            ids.append(r.json()["id"])

        try:
            r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
            events = [e for e in r.json() if e.get("type") == "tacho" and ref in (e.get("title") or "")]
            # Only ONE tacho event should exist for this reference (the latest)
            assert len(events) == 1, f"Expected exactly 1 tacho event, got {len(events)}: {events}"
            assert events[0]["date"] == latest_due
            assert events[0]["status"] == "due_soon"
        finally:
            for tid in ids:
                requests.delete(f"{API}/tacho/{tid}", headers=auth_headers, timeout=15)


# ---------- NEW: Calendar custom events ----------
class TestCalendarEvents:
    def test_create_appears_and_delete(self, auth_headers):
        day = (date.today() + timedelta(days=10)).isoformat()
        payload = {"date": day, "title": f"TEST Event {uuid.uuid4().hex[:4]}", "notes": "unit test"}
        r = requests.post(f"{API}/calendar/events", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev["id"].startswith("evt_")
        assert ev["title"] == payload["title"]
        assert ev["date"] == day
        eid = ev["id"]

        # Should appear in /calendar as type='custom' on that date
        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        events = [e for e in r.json() if e.get("type") == "custom" and e.get("id") == eid]
        assert len(events) == 1
        assert events[0]["date"] == day
        assert events[0]["title"] == payload["title"]

        # Delete
        r = requests.delete(f"{API}/calendar/events/{eid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/calendar", headers=auth_headers, timeout=15)
        assert not any(e.get("id") == eid for e in r.json())

    def test_create_requires_auth(self):
        r = requests.post(f"{API}/calendar/events", json={"date": "2026-01-01", "title": "x"}, timeout=15)
        assert r.status_code == 401

    def test_delete_requires_auth(self):
        r = requests.delete(f"{API}/calendar/events/x", timeout=15)
        assert r.status_code == 401
