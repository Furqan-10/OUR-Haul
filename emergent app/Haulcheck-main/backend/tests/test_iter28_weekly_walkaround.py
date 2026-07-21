"""Backend tests for Weekly Vehicle Walkaround feature (iteration 28).

Covers:
- Manager CRUD on /api/weekly-walkarounds
- Idempotent upsert per (user_id, vehicle_reg, week_start Monday)
- PDF sheet endpoint
- Driver GET /api/driver/weekly-walkaround and POST /api/driver/weekly-walkaround/day
- Defect submission creates an alert and updates the SAME sheet
- Cross-token isolation (manager token rejected on /driver, driver rejected on /weekly-walkarounds)
- Regression: /api/walkarounds (daily) still works and /api/driver/walkaround still works
"""
import os
import time
import requests
import pytest
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fall back to the file-based env (tests may run outside a shell with FRONT env)
    try:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL is required"

MANAGER_EMAIL = "manager@haulcheck.co.uk"
MANAGER_PASSWORD = "Test1234!"


def _monday_iso(d=None):
    d = d or datetime.now(timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def _today_key():
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][datetime.now(timezone.utc).weekday()]


# ---------------- Fixtures ----------------
@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD}, timeout=20)
    if r.status_code != 200:
        # try register
        r2 = requests.post(f"{BASE_URL}/api/auth/register",
                           json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD,
                                 "name": "Fleet Manager", "role": "manager"}, timeout=20)
        assert r2.status_code in (200, 201), r2.text
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def mheaders(manager_token):
    return {"Authorization": f"Bearer {manager_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def vehicle_reg(mheaders):
    """Ensure a vehicle called TESTWK 01 exists — create if missing."""
    reg = "TESTWK 01"
    veh_list = requests.get(f"{BASE_URL}/api/vehicles", headers=mheaders, timeout=20).json()
    existing = next((v for v in veh_list if v.get("registration") == reg), None)
    if existing:
        return reg
    r = requests.post(f"{BASE_URL}/api/vehicles", headers=mheaders,
                      json={"registration": reg, "make": "TEST", "model": "MODEL"}, timeout=20)
    assert r.status_code in (200, 201), r.text
    return reg


@pytest.fixture(scope="module")
def driver_and_code(mheaders, vehicle_reg):
    """Create (or reuse) a driver 'TEST_WK_DRV' assigned to vehicle_reg, return (driver_id, code)."""
    drivers = requests.get(f"{BASE_URL}/api/drivers", headers=mheaders, timeout=20).json()
    d = next((x for x in drivers if x.get("name") == "TEST_WK_DRV"), None)
    if not d:
        r = requests.post(f"{BASE_URL}/api/drivers", headers=mheaders,
                          json={"name": "TEST_WK_DRV", "assigned_vehicle_reg": vehicle_reg},
                          timeout=20)
        assert r.status_code in (200, 201), r.text
        d = r.json()
    else:
        # ensure vehicle assignment
        requests.put(f"{BASE_URL}/api/drivers/{d['id']}", headers=mheaders,
                     json={"assigned_vehicle_reg": vehicle_reg}, timeout=20)
    r = requests.post(f"{BASE_URL}/api/drivers/{d['id']}/access-code", headers=mheaders, timeout=20)
    assert r.status_code == 200, r.text
    return d["id"], r.json().get("access_code")


@pytest.fixture(scope="module")
def driver_token(driver_and_code):
    _, code = driver_and_code
    r = requests.post(f"{BASE_URL}/api/driver/login", json={"code": code}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def dheaders(driver_token):
    return {"Authorization": f"Bearer {driver_token}", "Content-Type": "application/json"}


# ---------------- Cleanup helper ----------------
@pytest.fixture(autouse=True, scope="module")
def _cleanup(mheaders, vehicle_reg):
    yield
    # Delete any weekly sheets for this test vehicle
    try:
        wl = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20).json()
        for w in wl:
            if w.get("vehicle_reg") == vehicle_reg:
                requests.delete(f"{BASE_URL}/api/weekly-walkarounds/{w['id']}", headers=mheaders, timeout=20)
    except Exception:
        pass


# ---------------- Tests: Manager CRUD ----------------
class TestWeeklyManagerCRUD:
    def test_list_endpoint_returns_list(self, mheaders):
        r = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_sheet(self, mheaders, vehicle_reg):
        payload = {"vehicle_reg": vehicle_reg, "driver_name": "TEST_WK_DRV",
                   "week_start": _monday_iso(), "mileage_start": "1000"}
        r = requests.post(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["vehicle_reg"] == vehicle_reg
        assert data["week_start"] == _monday_iso()
        assert data["mileage_start"] == "1000"
        assert data["driver_name"] == "TEST_WK_DRV"
        assert "id" in data and data["id"].startswith("wwc_")
        # persistence
        wl = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20).json()
        assert any(w["id"] == data["id"] for w in wl)

    def test_create_is_idempotent_same_week(self, mheaders, vehicle_reg):
        """Posting again for the same (vehicle, week) should upsert, not create a new sheet."""
        payload = {"vehicle_reg": vehicle_reg, "driver_name": "TEST_WK_DRV",
                   "week_start": _monday_iso(), "mileage_start": "1000"}
        r1 = requests.post(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, json=payload, timeout=20)
        r2 = requests.post(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, json=payload, timeout=20)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"], "Second POST created a NEW sheet instead of upserting"

    def test_week_start_snaps_to_monday(self, mheaders, vehicle_reg):
        # Send a Wednesday-of-next-week ISO date; expect week_start to be that Wed's Monday
        d = datetime.now(timezone.utc).date() + timedelta(days=(2 - datetime.now(timezone.utc).date().weekday()) % 7 + 7)
        expected_monday = (d - timedelta(days=d.weekday())).isoformat()
        payload = {"vehicle_reg": vehicle_reg, "week_start": d.isoformat(), "mileage_start": "2000"}
        r = requests.post(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["week_start"] == expected_monday
        # cleanup
        requests.delete(f"{BASE_URL}/api/weekly-walkarounds/{r.json()['id']}", headers=mheaders, timeout=20)

    def test_update_full_editor(self, mheaders, vehicle_reg):
        # create/upsert current-week sheet
        payload = {"vehicle_reg": vehicle_reg, "driver_name": "TEST_WK_DRV",
                   "week_start": _monday_iso(), "mileage_start": "1000"}
        r = requests.post(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, json=payload, timeout=20)
        wid = r.json()["id"]

        # simulate manager grid input: mon has 2 ticks + 1 cross
        days = {
            "mon": {
                "date": _monday_iso(),
                "checklist": [
                    {"section": "INTERNAL CHECKS", "item": "Mirrors and glass", "ok": True, "note": ""},
                    {"section": "INTERNAL CHECKS", "item": "Horn", "ok": True, "note": ""},
                    {"section": "EXTERNAL CHECKS", "item": "Tyres and wheel fixing", "ok": False,
                     "note": "Nail in offside rear"},
                ],
                "result": "defects_found",
            }
        }
        upd = {"mileage_finish": "1250", "days": days,
               "fault_reporting": "Nail in offside rear tyre — booked for repair Wed.",
               "driver_signature": "data:image/png;base64,SIG=="}
        r2 = requests.put(f"{BASE_URL}/api/weekly-walkarounds/{wid}", headers=mheaders, json=upd, timeout=20)
        assert r2.status_code == 200, r2.text

        # GET back and verify persistence
        wl = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20).json()
        fetched = next(w for w in wl if w["id"] == wid)
        assert fetched["mileage_finish"] == "1250"
        assert fetched["fault_reporting"].startswith("Nail")
        assert fetched["driver_signature"].startswith("data:image/png")
        assert len(fetched["days"]["mon"]["checklist"]) == 3
        oks = [c["ok"] for c in fetched["days"]["mon"]["checklist"]]
        assert oks == [True, True, False]
        # total mileage 1250 - 1000 = 250 (frontend computes; API stores raw strings)
        assert int(fetched["mileage_finish"]) - int(fetched["mileage_start"]) == 250

    def test_pdf_sheet_endpoint(self, mheaders, vehicle_reg):
        wl = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20).json()
        wid = next(w for w in wl if w.get("vehicle_reg") == vehicle_reg
                                    and w.get("week_start") == _monday_iso())["id"]
        r = requests.get(f"{BASE_URL}/api/weekly-walkarounds/{wid}/sheet", headers=mheaders, timeout=30)
        assert r.status_code == 200, r.text[:400]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "Response did not start with %PDF magic"
        assert len(r.content) > 1500  # sanity size
        # filename header includes the week
        cd = r.headers.get("content-disposition", "")
        assert "weekly-walkaround" in cd
        assert _monday_iso() in cd

    def test_pdf_sheet_404_for_missing(self, mheaders):
        r = requests.get(f"{BASE_URL}/api/weekly-walkarounds/wwc_doesnotexist/sheet",
                         headers=mheaders, timeout=20)
        assert r.status_code == 404


# ---------------- Tests: Driver flow ----------------
class TestWeeklyDriverFlow:
    def test_driver_gets_or_creates_current_week(self, dheaders):
        r = requests.get(f"{BASE_URL}/api/driver/weekly-walkaround", headers=dheaders, timeout=20)
        assert r.status_code == 200, r.text
        rec = r.json()
        assert rec["week_start"] == _monday_iso()
        assert "days" in rec

    def test_driver_submit_day_upserts_same_sheet_and_creates_alert(self, mheaders, dheaders, vehicle_reg):
        # ensure a clean current-week sheet exists — get its id
        rec_before = requests.get(f"{BASE_URL}/api/driver/weekly-walkaround", headers=dheaders, timeout=20).json()
        wid_before = rec_before["id"]

        # Submit a day with 1 defect
        checklist = [
            {"section": "INTERNAL CHECKS", "item": "Mirrors and glass", "ok": True, "note": ""},
            {"section": "EXTERNAL CHECKS", "item": "Lights and indicators", "ok": False, "note": "Nearside brake light out"},
        ]
        payload = {"vehicle_reg": vehicle_reg, "checklist": checklist, "mileage": "1050",
                   "signature": "data:image/png;base64,DRVSIG=="}
        r = requests.post(f"{BASE_URL}/api/driver/weekly-walkaround/day",
                          headers=dheaders, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        submitted = r.json()

        # same sheet id (upsert)
        assert submitted["id"] == wid_before

        # today's chip filled
        tk = _today_key()
        assert tk in submitted["days"], f"day '{tk}' missing"
        assert submitted["days"][tk]["result"] == "defects_found"
        items = [c["item"] for c in submitted["days"][tk]["checklist"]]
        assert "Lights and indicators" in items

        # signature should be set (first time in the week)
        assert submitted["driver_signature"].startswith("data:image/png")

        # Alert should be created on manager side
        # give a moment for insertion
        time.sleep(0.3)
        alerts = requests.get(f"{BASE_URL}/api/alerts", headers=mheaders, timeout=20).json()
        # find newest matching alert
        recent = [a for a in alerts
                  if a.get("type") == "walkaround_defect"
                  and vehicle_reg in (a.get("title") or "")
                  and "Lights and indicators" in (a.get("message") or a.get("description") or "")]
        assert recent, f"No walkaround_defect alert created. alerts={[a.get('title') for a in alerts][:5]}"

        # Manager side lists sheet with today's column filled
        wl = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=mheaders, timeout=20).json()
        mgr_view = next(w for w in wl if w["id"] == wid_before)
        assert tk in mgr_view["days"]
        assert len(mgr_view["days"][tk]["checklist"]) == 2

    def test_second_driver_submit_does_not_create_new_sheet(self, dheaders, vehicle_reg):
        # Submit again — should still be same wid, same week
        r1 = requests.get(f"{BASE_URL}/api/driver/weekly-walkaround", headers=dheaders, timeout=20).json()
        wid1 = r1["id"]
        payload = {"vehicle_reg": vehicle_reg,
                   "checklist": [{"section": "INTERNAL CHECKS", "item": "Horn", "ok": True, "note": ""}],
                   "mileage": "1080", "signature": ""}
        r2 = requests.post(f"{BASE_URL}/api/driver/weekly-walkaround/day",
                           headers=dheaders, json=payload, timeout=20)
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == wid1
        # mileage_finish updated to latest
        assert r2.json()["mileage_finish"] == "1080"


# ---------------- Tests: Auth isolation ----------------
class TestAuthIsolation:
    def test_manager_token_rejected_on_driver_endpoint(self, mheaders):
        r = requests.get(f"{BASE_URL}/api/driver/weekly-walkaround", headers=mheaders, timeout=20)
        assert r.status_code in (401, 403)

    def test_driver_token_rejected_on_manager_endpoint(self, dheaders):
        r = requests.get(f"{BASE_URL}/api/weekly-walkarounds", headers=dheaders, timeout=20)
        assert r.status_code in (401, 403)

    def test_unauth_rejected(self):
        r = requests.get(f"{BASE_URL}/api/weekly-walkarounds", timeout=20)
        assert r.status_code in (401, 403)


# ---------------- Regression: Daily walkaround still works ----------------
class TestDailyWalkaroundRegression:
    def test_manager_list_daily(self, mheaders):
        r = requests.get(f"{BASE_URL}/api/walkarounds", headers=mheaders, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_driver_daily_submit(self, dheaders, vehicle_reg):
        payload = {
            "vehicle_reg": vehicle_reg,
            "checklist": [{"section": "INTERNAL CHECKS", "item": "Mirrors and glass", "ok": True, "note": ""}],
            "notes": "",
            "signature": "data:image/png;base64,DAILYSIG==",
        }
        r = requests.post(f"{BASE_URL}/api/driver/walkaround", headers=dheaders, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        rec = r.json()
        assert rec.get("vehicle_reg") == vehicle_reg
        assert rec.get("result") in ("nil_defect", "defects_found")
