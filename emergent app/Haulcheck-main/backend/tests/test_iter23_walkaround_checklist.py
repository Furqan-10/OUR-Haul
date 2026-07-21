"""
Iteration 23 - HGV Daily Walkaround Checklist
Tests that walkaround endpoints persist and return the DVSA checklist array
and that the walkaround PDF report can be downloaded (application/pdf).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

EMAIL = "manager@haulcheck.co.uk"
PASSWORD = "Test1234!"

CHECKLIST_SECTIONS = {
    "Internal Checks": [
        "Mirrors and glass", "Windscreen wipers and washers", "Front view", "Warning lamps",
        "Steering", "Horn", "Brakes and air build-up", "Height marker", "Seatbelts",
    ],
    "External Checks": [
        "Lights and indicators", "Fuel/oil leaks", "Battery security and condition",
        "Diesel exhaust fluid (AdBlue)", "Excessive engine exhaust smoke",
        "Security of body/wings", "Spray suppression", "Tyres and wheel fixing",
        "Brake line", "Electrical connections", "Coupling security", "Security of load",
        "Number plate", "Reflectors and lights", "Markers",
    ],
}


def build_checklist(fail_indices=None, notes=None):
    fail_indices = set(fail_indices or [])
    notes = notes or {}
    checklist = []
    idx = 0
    for section, items in CHECKLIST_SECTIONS.items():
        for item in items:
            ok = idx not in fail_indices
            checklist.append({
                "section": section,
                "item": item,
                "ok": ok,
                "note": "" if ok else notes.get(idx, "Test defect"),
            })
            idx += 1
    return checklist


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def cleanup_ids():
    return []


def test_login_ok(token):
    assert token


def test_create_walkaround_nil_defect_with_checklist(client, cleanup_ids):
    payload = {
        "vehicle_reg": "AB12 CDE",
        "driver_name": "",
        "check_date": "2026-01-15",
        "result": "nil_defect",
        "mileage": "12345",
        "defects_noted": "",
        "checklist": build_checklist(),
        "attachments": [],
    }
    r = client.post(f"{BASE_URL}/api/walkarounds", json=payload)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data.get("id")
    assert data["vehicle_reg"] == "AB12 CDE"
    assert data["result"] == "nil_defect"
    assert isinstance(data.get("checklist"), list)
    assert len(data["checklist"]) == 24
    assert all(c["ok"] for c in data["checklist"])
    # verify sections + items are stored
    internal = [c for c in data["checklist"] if c["section"] == "Internal Checks"]
    external = [c for c in data["checklist"] if c["section"] == "External Checks"]
    assert len(internal) == 9
    assert len(external) == 15
    cleanup_ids.append(data["id"])


def test_create_walkaround_defects_found_with_checklist(client, cleanup_ids):
    payload = {
        "vehicle_reg": "BX20 XYZ",
        "driver_name": "",
        "check_date": "2026-01-15",
        "result": "defects_found",
        "mileage": "5000",
        "defects_noted": "Mirrors and glass: cracked; Lights and indicators: nsf out",
        "checklist": build_checklist(
            fail_indices=[0, 9],
            notes={0: "cracked", 9: "nsf out"},
        ),
        "attachments": [],
    }
    r = client.post(f"{BASE_URL}/api/walkarounds", json=payload)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["result"] == "defects_found"
    cl = data.get("checklist") or []
    assert len(cl) == 24
    failed = [c for c in cl if not c["ok"]]
    assert len(failed) == 2
    failed_items = {c["item"] for c in failed}
    assert "Mirrors and glass" in failed_items
    assert "Lights and indicators" in failed_items
    cleanup_ids.append(data["id"])


def test_list_walkarounds_includes_checklist(client, cleanup_ids):
    r = client.get(f"{BASE_URL}/api/walkarounds")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    # find the two we created
    for wid in cleanup_ids:
        match = next((x for x in items if x["id"] == wid), None)
        assert match, f"Created walkaround {wid} not found in list"
        assert "checklist" in match
        assert isinstance(match["checklist"], list)
        assert len(match["checklist"]) == 24
        # verify structure of a checklist item
        c0 = match["checklist"][0]
        assert set(c0.keys()) >= {"section", "item", "ok", "note"}


def test_rectify_defects_found_walkaround(client, cleanup_ids):
    # rectify the second (defects_found) walkaround
    wid = cleanup_ids[1]
    r = client.put(
        f"{BASE_URL}/api/walkarounds/{wid}/rectify",
        json={"rectified_date": "2026-01-16", "rectified_notes": "Replaced glass and bulb"},
    )
    assert r.status_code == 200, r.text
    # verify via list
    r2 = client.get(f"{BASE_URL}/api/walkarounds")
    match = next(x for x in r2.json() if x["id"] == wid)
    assert match["rectified"] is True
    assert match["rectified_date"] == "2026-01-16"
    assert "Replaced glass" in match["rectified_notes"]


def test_walkaround_pdf_report(client):
    r = client.get(f"{BASE_URL}/api/reports/walkaround")
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert "application/pdf" in ct, f"Unexpected content-type: {ct}"
    assert len(r.content) > 500
    # PDF magic bytes
    assert r.content[:4] == b"%PDF"


def test_walkaround_report_json_has_checks_column(client):
    """Verify that the JSON version of walkaround report includes 'Checks' column."""
    r = client.get(f"{BASE_URL}/api/reports/walkaround?format=json")
    assert r.status_code == 200, r.text
    data = r.json()
    sections = data.get("sections") or []
    assert sections, "No sections in walkaround report"
    wa_section = next((s for s in sections if s.get("heading") == "Daily Walkaround Checks"), None)
    assert wa_section, "Daily Walkaround Checks section missing"
    cols = wa_section.get("columns") or []
    assert "Checks" in cols, f"'Checks' column missing from walkaround report columns: {cols}"
    # If we created walkarounds with checklists, verify the Checks cell format like '24/24' or '22/24'
    checks_idx = cols.index("Checks")
    rows = wa_section.get("rows") or []
    if rows:
        sample_cells = rows[0].get("cells") or []
        checks_val = sample_cells[checks_idx] if len(sample_cells) > checks_idx else None
        assert checks_val is not None
        # accept "N/N" or em-dash for old rows
        assert "/" in str(checks_val) or checks_val == "—"


def test_cleanup(client, cleanup_ids):
    for wid in cleanup_ids:
        client.delete(f"{BASE_URL}/api/walkarounds/{wid}")
