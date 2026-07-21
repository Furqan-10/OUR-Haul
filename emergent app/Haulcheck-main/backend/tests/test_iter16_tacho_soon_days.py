"""
Iteration 16 backend tests — Tacho "due soon" threshold fix.

Bug: `compliance_status(days)` used a fixed 30-day 'due soon' window, so a
freshly-logged 28-day-cycle tacho download was always flagged 'due soon'.

Fix (server.py):
  - `compliance_status(days, soon_days: int = 30)` now accepts a configurable
    window (~line 88).
  - `TACHO_SOON_DAYS = 7` (~line 98).
  - Applied with soon_days=TACHO_SOON_DAYS at:
      * GET /api/tacho list (~line 1457)
      * gather_stats tacho alerts (~line 2062)
      * calendar tacho events (~line 1894)

We verify via:
  * POST /api/tacho + GET /api/tacho -> record.status / days_left
  * GET /api/dashboard/stats -> alerts[].{type,name,item,status,days}
  * POST /api/ai/risk-insight -> deterministic checklist (not the LLM prose)

Non-tacho windows (vehicle mot_due) stay at 30-day 'due soon'.
"""
import os
import uuid
import requests
import pytest
from pathlib import Path
from datetime import date, timedelta

# ---------- Config ----------
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
API = f"{BASE_URL}/api"

SEED_EMAIL = "manager@haulcheck.co.uk"
SEED_PASSWORD = "Test1234!"


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login_or_register(email, password, name="Fleet Manager"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code == 200:
        return r.json()["token"]
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name}, timeout=20)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def token():
    return _login_or_register(SEED_EMAIL, SEED_PASSWORD)


# ---------- Helpers ----------
def _iso(d: date) -> str:
    return d.isoformat()


def _today() -> date:
    return date.today()


def _post_tacho(token, source_type, reference, last_download: str, frequency_days: int = 28):
    r = requests.post(f"{API}/tacho", json={
        "source_type": source_type,
        "reference": reference,
        "frequency_days": frequency_days,
        "last_download": last_download,
        "infringements": 0,
        "notes": "TEST iter16",
        "attachments": [],
    }, headers=_headers(token), timeout=15)
    assert r.status_code == 200, f"POST /api/tacho failed: {r.status_code} {r.text}"
    return r.json()


def _get_tacho(token):
    r = requests.get(f"{API}/tacho", headers=_headers(token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _get_stats(token):
    # Actual endpoint is GET /api/dashboard (review-request called it /dashboard/stats).
    r = requests.get(f"{API}/dashboard", headers=_headers(token), timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _get_calendar(token):
    r = requests.get(f"{API}/calendar", headers=_headers(token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _risk_insight(token):
    r = requests.post(f"{API}/ai/risk-insight", headers=_headers(token), timeout=90)
    assert r.status_code == 200, f"risk-insight HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "checklist" in body and isinstance(body["checklist"], list), f"missing checklist: {body}"
    return body


def _delete(token, path):
    return requests.delete(f"{API}{path}", headers=_headers(token), timeout=15)


def _find_tacho_alerts_by_name(alerts, name):
    return [a for a in alerts if a.get("type") == "tacho" and a.get("name") == name]


def _find_tacho_by_ref(tacho_list, reference):
    return [t for t in tacho_list if t.get("reference") == reference]


# ==============================================================
# 1. Tacho download NOT 'due soon' when 28 days out
# ==============================================================
class TestTachoFarNotDueSoon:
    def test_fresh_download_28_days_out_is_valid(self, token):
        ref = f"QA Far Driver {uuid.uuid4().hex[:6]}"
        today = _today()
        created = _post_tacho(token, "Driver Card", ref, last_download=_iso(today), frequency_days=28)
        tid = created["id"]
        try:
            # 1a. GET /api/tacho -> record status/days_left
            tacho_list = _get_tacho(token)
            rows = _find_tacho_by_ref(tacho_list, ref)
            assert rows, f"POSTed tacho not found on GET /api/tacho for reference={ref!r}"
            row = rows[0]
            assert row.get("days_left") is not None and 26 <= row["days_left"] <= 29, (
                f"days_left expected ~28, got {row.get('days_left')} (next_due={row.get('next_due')})"
            )
            assert row.get("status") == "valid", (
                f"Fresh 28-day-cycle download should be 'valid' (>7 days), got status={row.get('status')} "
                f"days_left={row.get('days_left')}"
            )

            # 1b. Dashboard stats -> no tacho alert for this reference
            stats = _get_stats(token)
            alerts = stats.get("alerts") or []
            hits = _find_tacho_alerts_by_name(alerts, ref)
            assert not hits, (
                f"Dashboard should NOT flag a tacho alert for a 28-day-out download. Got: {hits}"
            )

            # 1c. risk-insight checklist -> no tacho 'due soon' for this reference
            body = _risk_insight(token)
            checklist = body["checklist"]
            bad = [g for g in checklist
                   if g.get("area") == "Tacho"
                   and "due soon" in (g.get("item") or "").lower()
                   and ref.lower() in (g.get("item") or "").lower()]
            assert not bad, f"risk-insight checklist should not raise a tacho 'due soon' for {ref}. Got: {bad}"
        finally:
            _delete(token, f"/tacho/{tid}")


# ==============================================================
# 2. Tacho download IS 'due soon' when ~5 days out
# ==============================================================
class TestTachoNearIsDueSoon:
    def test_download_23_days_ago_is_due_soon(self, token):
        ref = f"QA Near Driver {uuid.uuid4().hex[:6]}"
        last = _today() - timedelta(days=23)  # next_due ~5 days from today
        created = _post_tacho(token, "Driver Card", ref, last_download=_iso(last), frequency_days=28)
        tid = created["id"]
        try:
            # 2a. record status
            tacho_list = _get_tacho(token)
            rows = _find_tacho_by_ref(tacho_list, ref)
            assert rows, f"POSTed tacho not found on GET /api/tacho for reference={ref!r}"
            row = rows[0]
            assert row.get("days_left") is not None and 3 <= row["days_left"] <= 7, (
                f"days_left expected ~5, got {row.get('days_left')} (next_due={row.get('next_due')})"
            )
            assert row.get("status") == "due_soon", (
                f"23-days-ago download on 28-day cycle should be 'due_soon' (within 7-day tacho window). "
                f"Got status={row.get('status')} days_left={row.get('days_left')}"
            )

            # 2b. dashboard alerts SHOULD contain a tacho due_soon for this reference
            stats = _get_stats(token)
            alerts = stats.get("alerts") or []
            hits = _find_tacho_alerts_by_name(alerts, ref)
            assert hits, (
                f"Dashboard should flag a tacho alert for {ref} (~5 days out). "
                f"Alerts of type=tacho: {[a for a in alerts if a.get('type')=='tacho']}"
            )
            assert any(a.get("status") == "due_soon" for a in hits), (
                f"Expected due_soon in tacho alert for {ref}, got: {hits}"
            )
        finally:
            _delete(token, f"/tacho/{tid}")


# ==============================================================
# 3. Boundary: ~10 days out is 'valid' (10 > 7-day tacho window)
# ==============================================================
class TestTachoBoundary10DaysValid:
    def test_10_days_out_is_valid(self, token):
        ref = f"QA Boundary Driver {uuid.uuid4().hex[:6]}"
        last = _today() - timedelta(days=18)  # next_due ~10 days from today
        created = _post_tacho(token, "Driver Card", ref, last_download=_iso(last), frequency_days=28)
        tid = created["id"]
        try:
            tacho_list = _get_tacho(token)
            rows = _find_tacho_by_ref(tacho_list, ref)
            assert rows, f"POSTed tacho not found for reference={ref!r}"
            row = rows[0]
            assert row.get("days_left") is not None and 8 <= row["days_left"] <= 12, (
                f"days_left expected ~10, got {row.get('days_left')} (next_due={row.get('next_due')})"
            )
            assert row.get("status") == "valid", (
                f"10-days-out tacho download should be 'valid' (10 > 7-day window). "
                f"Got status={row.get('status')} days_left={row.get('days_left')}"
            )

            # No dashboard tacho alert either
            stats = _get_stats(token)
            hits = _find_tacho_alerts_by_name(stats.get("alerts") or [], ref)
            assert not hits, f"No tacho alert expected for 10-days-out download, got: {hits}"
        finally:
            _delete(token, f"/tacho/{tid}")


# ==============================================================
# 4. Non-tacho windows unchanged — vehicle mot_due at +20 days still due_soon
# ==============================================================
class TestVehicleMotStill30DayWindow:
    def test_vehicle_mot_20_days_out_is_due_soon(self, token):
        reg = f"QA-MOT-{uuid.uuid4().hex[:5].upper()}"
        mot_due = _iso(_today() + timedelta(days=20))
        r = requests.post(f"{API}/vehicles", json={
            "registration": reg,
            "type": "HGV",
            "make": "Volvo",
            "model": "FH",
            "mot_due": mot_due,
        }, headers=_headers(token), timeout=15)
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        try:
            vlist = requests.get(f"{API}/vehicles", headers=_headers(token), timeout=15)
            assert vlist.status_code == 200, vlist.text
            match = [v for v in vlist.json() if v.get("registration") == reg]
            assert match, f"vehicle {reg} not found in GET /api/vehicles"
            v = match[0]
            assert v.get("mot_status") == "due_soon", (
                f"Vehicle mot_due at +20 days should stay 'due_soon' (30-day window). "
                f"Got mot_status={v.get('mot_status')} mot_due={v.get('mot_due')}"
            )
        finally:
            _delete(token, f"/vehicles/{vid}")


# ==============================================================
# 5. Regression — dashboard/stats, tacho list, calendar, risk-insight OK
# ==============================================================
class TestRegressionEndpoints:
    def test_dashboard_stats_shape(self, token):
        stats = _get_stats(token)
        assert isinstance(stats, dict)
        assert "alerts" in stats and isinstance(stats["alerts"], list)
        for a in stats["alerts"]:
            assert "type" in a and "item" in a and "status" in a

    def test_tacho_list_shape(self, token):
        tacho = _get_tacho(token)
        assert isinstance(tacho, list)
        for t in tacho:
            # Every record should have status computed with the 7-day tacho window
            if t.get("next_due"):
                assert t.get("status") in ("valid", "due_soon", "expired", "unknown")

    def test_calendar_shape(self, token):
        cal = _get_calendar(token)
        assert isinstance(cal, list) or isinstance(cal, dict), f"Unexpected calendar type: {type(cal)}"

    def test_risk_insight_shape(self, token):
        body = _risk_insight(token)
        assert isinstance(body.get("checklist"), list)
        assert isinstance(body.get("insight"), str) and body["insight"]
        assert isinstance(body.get("score"), int) and 0 <= body["score"] <= 100
