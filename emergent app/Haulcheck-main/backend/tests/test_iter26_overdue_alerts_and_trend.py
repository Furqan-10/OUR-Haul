"""
Iteration 26 backend regression:
- Overdue auto-alerts (dedup + severity + dismiss persistence + auto-clear on renewal)
- Compliance trend history (GET /api/dashboard snapshots + GET /api/compliance/history)
- Reminder settings + send + run-scheduled (Resend test mode; graceful 500 OK)
"""

import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://transport-verify-3.preview.emergentagent.com").rstrip("/")
MANAGER_EMAIL = "manager@haulcheck.co.uk"
MANAGER_PASSWORD = "Test1234!"
THROTTLE_SECONDS = 125  # sync_overdue_alerts throttle is 120s


# ---------- Shared fixtures ----------

@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(api):
    # login
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    if r.status_code != 200:
        # attempt registration
        api.post(f"{BASE_URL}/api/auth/register", json={
            "email": MANAGER_EMAIL, "password": MANAGER_PASSWORD, "name": "Test Manager", "role": "manager"
        })
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token")
    assert tok, "No token in login response"
    return tok


@pytest.fixture(scope="module")
def client(api, token):
    api.headers.update({"Authorization": f"Bearer {token}"})
    return api


# ---------- 1. Overdue alerts generated + severity mapping ----------

class TestOverdueGeneration:
    def test_alerts_endpoint_returns_list(self, client):
        r = client.get(f"{BASE_URL}/api/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_overdue_alerts_present(self, client):
        """Manager account has AB12 CDE with MOT + PMI overdue → expect overdue alerts."""
        alerts = client.get(f"{BASE_URL}/api/alerts").json()
        overdue = [a for a in alerts if a.get("type") == "overdue"]
        assert len(overdue) >= 1, f"Expected at least one overdue alert, got {len(overdue)}"
        # All overdue alerts must have dedup_key
        for a in overdue:
            assert a.get("dedup_key"), f"Overdue alert missing dedup_key: {a}"
            assert a["dedup_key"].startswith("overdue|"), f"Bad dedup_key format: {a['dedup_key']}"
            assert a.get("severity") in ("safety_critical", "major", "minor")
            assert a.get("title")
            assert a.get("message")

    def test_severity_mapping_mot_safety_critical(self, client):
        alerts = client.get(f"{BASE_URL}/api/alerts").json()
        mot = [a for a in alerts if a.get("type") == "overdue" and "MOT" in (a.get("title") or "")]
        if mot:
            for a in mot:
                assert a["severity"] == "safety_critical", f"MOT overdue should be safety_critical, got {a['severity']}"


# ---------- 2. Dedup stability ----------

class TestDedupStability:
    def test_repeated_calls_no_duplicates(self, client):
        """Within the 120s throttle window, extra calls MUST NOT create dupes."""
        r1 = client.get(f"{BASE_URL}/api/alerts").json()
        r2 = client.get(f"{BASE_URL}/api/alerts").json()
        r3 = client.get(f"{BASE_URL}/api/alerts").json()
        n1 = len([a for a in r1 if a.get("type") == "overdue"])
        n2 = len([a for a in r2 if a.get("type") == "overdue"])
        n3 = len([a for a in r3 if a.get("type") == "overdue"])
        assert n1 == n2 == n3, f"Overdue counts drifted: {n1}/{n2}/{n3}"

        # No two overdue alerts share the same dedup_key
        keys = [a["dedup_key"] for a in r1 if a.get("type") == "overdue"]
        assert len(keys) == len(set(keys)), f"Duplicate dedup_keys detected: {keys}"

    def test_unread_count_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/alerts/unread-count")
        assert r.status_code == 200
        d = r.json()
        assert "count" in d
        assert isinstance(d["count"], int)


# ---------- 3. Compliance history + dashboard snapshot ----------

class TestComplianceHistory:
    def test_dashboard_records_snapshot(self, client):
        r = client.get(f"{BASE_URL}/api/dashboard")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "risk_score" in data
        assert "risk_band" in data
        assert isinstance(data["risk_score"], int)
        assert data["risk_band"] in ("Low Risk", "Moderate Risk", "High Risk")
        assert "registered_users" in data
        assert isinstance(data["registered_users"], int)
        assert data["registered_users"] >= 1

    def test_history_returns_snapshot(self, client):
        # Trigger snapshot via dashboard
        client.get(f"{BASE_URL}/api/dashboard")
        r = client.get(f"{BASE_URL}/api/compliance/history?days=90")
        assert r.status_code == 200, r.text
        body = r.json()
        # backend returns {"history": [...]} — frontend uses res.data.history
        assert "history" in body, f"Expected 'history' key in response, got: {body}"
        rows = body["history"]
        assert isinstance(rows, list)
        assert len(rows) >= 1, "Expected at least one snapshot after hitting /dashboard"
        row = rows[-1]
        for k in ("date", "score", "band", "expired", "due_soon"):
            assert k in row, f"Missing field {k} in history row: {row}"
        # Ascending by date
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates), f"History not sorted ascending: {dates}"

    def test_history_upserts_same_day(self, client):
        """Multiple /dashboard hits on the same day should NOT duplicate rows."""
        for _ in range(3):
            client.get(f"{BASE_URL}/api/dashboard")
        rows = client.get(f"{BASE_URL}/api/compliance/history?days=90").json()["history"]
        today = rows[-1]["date"]
        same_day = [r for r in rows if r["date"] == today]
        assert len(same_day) == 1, f"Same-day snapshot duplicated: {len(same_day)} rows"


# ---------- 4. Reminder settings + send + run-scheduled ----------

class TestReminders:
    def test_get_settings(self, client):
        r = client.get(f"{BASE_URL}/api/reminders/settings")
        assert r.status_code == 200
        d = r.json()
        for k in ("recipients", "areas", "presets"):
            assert k in d, f"Missing {k} in reminders settings response"
        assert isinstance(d["areas"], list) and len(d["areas"]) > 0
        assert isinstance(d["presets"], (list, dict))

    def test_put_settings_saves_recipient(self, client):
        payload = {"recipients": [{"email": "TEST_reminders@example.com", "areas": [], "frequency": "daily"}]}
        r = client.put(f"{BASE_URL}/api/reminders/settings", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert any(x["email"] == "TEST_reminders@example.com" for x in d.get("recipients", []))
        # verify persistence via GET
        got = client.get(f"{BASE_URL}/api/reminders/settings").json()
        emails = [r["email"] for r in got["recipients"]]
        assert "TEST_reminders@example.com" in emails

    def test_send_reminders_no_500_bug(self, client):
        # Must have recipients configured first (previous test did this)
        r = client.post(f"{BASE_URL}/api/reminders/send")
        # Acceptable: 200 (success) or 500 with detail containing "Failed to send" (Resend layer).
        # NOT acceptable: 500 with code/exception traceback style, missing detail.
        assert r.status_code in (200, 500), f"Unexpected status: {r.status_code} {r.text}"
        if r.status_code == 500:
            detail = (r.json() or {}).get("detail", "")
            assert "Failed to send" in detail, f"500 without graceful 'Failed to send' detail: {detail}"

    def test_run_scheduled_no_500_bug(self, client):
        r = client.post(f"{BASE_URL}/api/reminders/run-scheduled")
        assert r.status_code in (200, 500), f"Unexpected status: {r.status_code} {r.text}"
        if r.status_code == 500:
            detail = (r.json() or {}).get("detail", "")
            assert "Failed to run" in detail, f"500 without graceful 'Failed to run' detail: {detail}"


# ---------- 5. Dismiss persistence + auto-clear on renewal (long test, single wait) ----------

class TestDismissAndAutoClear:
    """
    Uses ONE ~125s wait to bypass the sync_overdue_alerts throttle exactly once.
    Steps:
      1. Get initial overdue alerts
      2. Pick one → DELETE (dismiss) → verify removed from list
      3. Create a test vehicle with EXPIRED mot_due
      4. Wait 125s → GET /api/alerts → dismissed one is NOT recreated AND
         new test vehicle produces a new overdue alert
      5. PUT the vehicle to future mot_due → wait 125s → alert auto-cleared
    """

    @pytest.fixture(scope="class")
    def test_vehicle_id(self, client):
        reg = f"TEST{uuid.uuid4().hex[:4].upper()}"
        payload = {
            "registration": reg,
            "make": "TEST",
            "model": "OverdueTest",
            "mot_due": "2020-01-01",       # long-expired
            "service_due": "",
            "tax_due": "",
        }
        r = client.post(f"{BASE_URL}/api/vehicles", json=payload)
        assert r.status_code in (200, 201), f"Create vehicle failed: {r.status_code} {r.text}"
        vid = r.json().get("id")
        assert vid
        yield {"id": vid, "reg": reg}
        # cleanup
        try:
            client.delete(f"{BASE_URL}/api/vehicles/{vid}")
        except Exception:
            pass

    def test_full_dismiss_and_autoclear_lifecycle(self, client, test_vehicle_id):
        reg = test_vehicle_id["reg"]
        vid = test_vehicle_id["id"]

        # ---- Step A: initial GET so we have overdue alerts + reset throttle ----
        alerts = client.get(f"{BASE_URL}/api/alerts").json()
        overdue = [a for a in alerts if a.get("type") == "overdue"]
        assert overdue, "Need at least one overdue alert to test dismiss"
        target = overdue[0]
        target_key = target["dedup_key"]
        target_id = target["id"]

        # ---- Step B: dismiss it ----
        r = client.delete(f"{BASE_URL}/api/alerts/{target_id}")
        assert r.status_code == 200, r.text
        # Immediately verify it's gone
        after_delete = client.get(f"{BASE_URL}/api/alerts").json()
        assert not any(a.get("id") == target_id for a in after_delete), "Deleted alert still returned"

        # ---- Step C: wait past throttle (also lets new test vehicle be picked up) ----
        print(f"\n[iter26] Sleeping {THROTTLE_SECONDS}s to bypass sync_overdue_alerts throttle...")
        time.sleep(THROTTLE_SECONDS)

        after_wait = client.get(f"{BASE_URL}/api/alerts").json()
        overdue_keys = {a["dedup_key"] for a in after_wait if a.get("type") == "overdue"}

        # dismissed alert MUST NOT have been recreated
        assert target_key not in overdue_keys, (
            f"Dismissed alert (key={target_key}) was re-created after throttle window "
            f"— db.dismissed_alerts not honoured"
        )

        # new test vehicle should have produced an overdue alert
        new_alert = next(
            (a for a in after_wait if a.get("type") == "overdue" and reg in (a.get("title") or "")),
            None,
        )
        assert new_alert is not None, f"No overdue alert for test vehicle {reg}. Got: {[a.get('title') for a in after_wait if a.get('type')=='overdue']}"
        assert new_alert["severity"] == "safety_critical", f"MOT overdue should be safety_critical, got {new_alert['severity']}"

        # ---- Step D: renew the vehicle mot_due to a future date ----
        future = "2030-01-01"
        r = client.put(f"{BASE_URL}/api/vehicles/{vid}", json={
            "registration": reg, "make": "TEST", "model": "OverdueTest",
            "mot_due": future, "service_due": "", "tax_due": "",
        })
        assert r.status_code == 200, r.text

        # ---- Step E: wait another throttle window and verify auto-clear ----
        print(f"[iter26] Sleeping {THROTTLE_SECONDS}s again to test auto-clear-on-renewal...")
        time.sleep(THROTTLE_SECONDS)
        after_renew = client.get(f"{BASE_URL}/api/alerts").json()
        still_there = next(
            (a for a in after_renew if a.get("type") == "overdue" and reg in (a.get("title") or "")),
            None,
        )
        assert still_there is None, (
            f"Overdue alert for {reg} still present after mot_due was moved to {future}. "
            f"Alert: {still_there}"
        )
