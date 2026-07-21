"""
Iteration 15 backend tests — Tacho gap-detection fix.

Bug: detect_gaps() used to do an EXACT case-sensitive match of driver name /
vehicle reg against the tacho record's free-text `reference`, so any case /
whitespace / format difference caused a false 'no download record' gap.

Fix (server.py detect_gaps ~line 2146): a `_norm` helper (lower + collapse
whitespace) is applied to both sides; matching is bidirectional-substring.

We verify via POST /api/ai/risk-insight -> {insight, checklist, score}.
The LLM only writes the prose `insight` — the `checklist` field is deterministic
from detect_gaps, so we assert against `checklist` items.
"""
import os
import time
import uuid
import requests
import pytest
from pathlib import Path
from datetime import date

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


def _post_driver(token, name):
    r = requests.post(f"{API}/drivers", json={"name": name}, headers=_headers(token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _post_vehicle(token, reg):
    r = requests.post(f"{API}/vehicles", json={"registration": reg, "type": "HGV", "make": "Volvo", "model": "FH"},
                      headers=_headers(token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _post_tacho(token, source_type, reference, last_download=None, frequency_days=28):
    if last_download is None:
        last_download = date.today().isoformat()
    r = requests.post(f"{API}/tacho", json={
        "source_type": source_type,
        "reference": reference,
        "frequency_days": frequency_days,
        "last_download": last_download,
        "infringements": 0,
        "notes": "TEST iter15",
        "attachments": [],
    }, headers=_headers(token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _delete(token, path):
    return requests.delete(f"{API}{path}", headers=_headers(token), timeout=15)


def _risk_insight(token):
    r = requests.post(f"{API}/ai/risk-insight", headers=_headers(token), timeout=90)
    assert r.status_code == 200, f"risk-insight HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "checklist" in body and isinstance(body["checklist"], list), f"missing checklist: {body}"
    assert "insight" in body
    assert "score" in body
    return body


# ==============================================================
# 1. Driver-card false positive is fixed
# ==============================================================
class TestDriverCardTachoGapFix:
    def test_no_false_positive_when_reference_case_and_whitespace_differ(self, token):
        driver_name = "QA Tacho Driver"
        driver = _post_driver(token, driver_name)
        did = driver["id"]
        # Reference has different case + double spaces
        tacho = _post_tacho(token, "Driver Card", "qa  tacho  driver")
        tid = tacho["id"]
        try:
            # next_due should be ~28 days out (fresh download today), not overdue
            assert tacho.get("next_due"), f"tacho next_due missing: {tacho}"
            assert tacho["next_due"] >= date.today().isoformat(), f"next_due already overdue: {tacho['next_due']}"

            body = _risk_insight(token)
            checklist = body["checklist"]
            bad_item = f"{driver_name}: no driver-card tacho download record"
            hits = [g for g in checklist if g.get("item") == bad_item]
            assert not hits, (
                f"FALSE POSITIVE: driver-card gap fired even though a matching (normalized) "
                f"tacho download exists. Bad items: {hits}"
            )
        finally:
            _delete(token, f"/tacho/{tid}")
            _delete(token, f"/drivers/{did}")

    def test_positive_case_still_fires_when_no_matching_download(self, token):
        # Unique driver name with NO matching tacho record
        driver_name = f"QA NoTacho {uuid.uuid4().hex[:6]}"
        driver = _post_driver(token, driver_name)
        did = driver["id"]
        try:
            body = _risk_insight(token)
            checklist = body["checklist"]
            wanted_item = f"{driver_name}: no driver-card tacho download record"
            hits = [g for g in checklist if g.get("item") == wanted_item]
            assert hits, (
                f"REGRESSION: the driver-card gap should still fire for a driver with no download record. "
                f"Expected item '{wanted_item}' in checklist. Got items: "
                f"{[g.get('item') for g in checklist if 'driver-card tacho' in g.get('item','')]}"
            )
            # And it should have priority medium per detect_gaps
            assert hits[0].get("priority") == "medium"
            assert hits[0].get("area") == "Tacho"
        finally:
            _delete(token, f"/drivers/{did}")


# ==============================================================
# 2. Vehicle-unit false positive is fixed
# ==============================================================
class TestVehicleUnitTachoGapFix:
    def test_no_false_positive_when_ref_case_differs(self, token):
        reg = "QA-VU-01"
        veh = _post_vehicle(token, reg)
        vid = veh["id"]
        tacho = _post_tacho(token, "Vehicle Unit", "qa-vu-01")  # lower case
        tid = tacho["id"]
        try:
            assert tacho.get("next_due")
            assert tacho["next_due"] >= date.today().isoformat()

            body = _risk_insight(token)
            checklist = body["checklist"]
            bad_item = f"{reg}: no vehicle-unit tacho download record"
            hits = [g for g in checklist if g.get("item") == bad_item]
            assert not hits, (
                f"FALSE POSITIVE: vehicle-unit gap fired despite normalized-match. Bad items: {hits}"
            )
        finally:
            _delete(token, f"/tacho/{tid}")
            _delete(token, f"/vehicles/{vid}")

    def test_positive_case_still_fires_for_vehicle_without_download(self, token):
        reg = f"QA-VU-{uuid.uuid4().hex[:4].upper()}"
        veh = _post_vehicle(token, reg)
        vid = veh["id"]
        try:
            body = _risk_insight(token)
            checklist = body["checklist"]
            wanted_item = f"{reg}: no vehicle-unit tacho download record"
            hits = [g for g in checklist if g.get("item") == wanted_item]
            assert hits, (
                f"REGRESSION: vehicle-unit gap should still fire for a vehicle with no download record. "
                f"Expected '{wanted_item}'."
            )
        finally:
            _delete(token, f"/vehicles/{vid}")


# ==============================================================
# 3. Regression: /api/ai/risk-insight still returns a valid response
# ==============================================================
class TestRiskInsightRegression:
    def test_risk_insight_shape_and_other_gaps(self, token):
        body = _risk_insight(token)
        assert isinstance(body.get("score"), int)
        assert 0 <= body["score"] <= 100
        assert isinstance(body.get("insight"), str) and body["insight"]
        checklist = body["checklist"]
        assert isinstance(checklist, list)
        # Every checklist item has area/item/priority
        for g in checklist:
            assert "area" in g and "item" in g and "priority" in g
            assert g["priority"] in ("high", "medium", "low")

        # Sanity: known gap-rule areas exist in the schema — we don't force any
        # specific gap because the manager seed data can change, but we do
        # confirm the aggregation returns the standard area set structure.
        areas = {g["area"] for g in checklist}
        # These areas are always defined in detect_gaps; if the manager has
        # any missing PMI/insurance/licence they should surface — but we only
        # assert the checklist is non-null and enumerable, since seed data
        # varies. We ALSO confirm the specific bug items don't randomly
        # appear for the manager's real fleet (they only appear when the
        # driver/vehicle has no matching normalized tacho record — which is
        # environment-dependent). So the strong assertion is just structure.
        assert areas.issubset({"Operator", "Documents", "Insurance", "Fleet", "PMI",
                               "Maintenance", "Tacho", "Drivers", "Training"}), (
            f"Unexpected areas in checklist: {areas}"
        )
