"""
Iteration 21 backend tests
- New tacho Infringement Analyser endpoints (analyse, list, delete, report)
- Expanded LETTER_GUIDES / documents draft for new templates
"""
import io
import os
import struct
import zlib
import pytest
import requests

def _load_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    return (v or "").rstrip("/")


BASE_URL = _load_url()
API = f"{BASE_URL}/api"

EMAIL = "manager@haulcheck.co.uk"
PASSWORD = "Test1234!"


def _png_bytes(text_hint: str = "tacho") -> bytes:
    """Build a minimal valid PNG (10x10 grey). The AI just needs a valid image;
    it will still return a well-formed JSON (0 infringements if unreadable)."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 10, 10, 8, 0, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\x80" * 10 for _ in range(10))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def uploaded_file_id(auth):
    files = {"file": ("tacho.png", _png_bytes(), "image/png")}
    r = requests.post(f"{API}/upload", headers=auth, files=files, timeout=30)
    assert r.status_code == 200, r.text
    fid = r.json().get("file_id")
    assert fid
    return fid


# ---------------- documents/draft with new templates ----------------

@pytest.mark.parametrize("template", [
    "Driver Infringement", "Infringement Report", "Attestation Record",
    "Indoctrination Document", "Adhoc Note", "Warning Letter",
])
def test_draft_new_letter_templates(auth, template):
    """Iter 21 — new templates should produce non-empty subject + body via AI."""
    r = requests.post(
        f"{API}/documents/draft",
        headers=auth,
        json={
            "template": template,
            "recipient_name": "John Smith",
            "points": "Exceeded 4.5h continuous driving on 2026-03-02",
        },
        timeout=90,
    )
    assert r.status_code == 200, f"{template} → {r.status_code} {r.text}"
    d = r.json()
    assert isinstance(d.get("subject"), str) and d["subject"].strip(), f"{template} missing subject"
    assert isinstance(d.get("body"), str) and len(d["body"]) > 50, f"{template} body too short"


# ---------------- Tacho analyser endpoints ----------------

def test_analyse_creates_persisted_analysis(auth, uploaded_file_id):
    r = requests.post(
        f"{API}/tacho/analyse",
        headers=auth,
        json={"file_id": uploaded_file_id, "driver_name": "TEST_John_Smith"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    a = r.json()
    # basic shape
    assert isinstance(a.get("id"), str) and a["id"].startswith("tan_")
    assert a.get("driver_name") == "TEST_John_Smith"
    assert isinstance(a.get("total_infringements"), int)
    assert isinstance(a.get("infringements"), list)
    assert isinstance(a.get("confidence"), (int, float))
    # persisted?
    lst = requests.get(f"{API}/tacho/analyses", headers=auth, timeout=15)
    assert lst.status_code == 200
    ids = [x["id"] for x in lst.json()]
    assert a["id"] in ids

    # PDF report
    pdf = requests.get(f"{API}/tacho/analyses/{a['id']}/report", headers=auth, timeout=30)
    assert pdf.status_code == 200
    assert pdf.headers.get("content-type", "").startswith("application/pdf")
    assert pdf.content[:4] == b"%PDF"
    assert len(pdf.content) > 500

    # bogus id -> 404
    bad = requests.get(f"{API}/tacho/analyses/tan_doesnotexist/report", headers=auth, timeout=15)
    assert bad.status_code == 404

    # delete
    dl = requests.delete(f"{API}/tacho/analyses/{a['id']}", headers=auth, timeout=15)
    assert dl.status_code == 200
    lst2 = requests.get(f"{API}/tacho/analyses", headers=auth, timeout=15)
    assert a["id"] not in [x["id"] for x in lst2.json()]


def test_analyse_unauth():
    r = requests.post(f"{API}/tacho/analyse", json={"file_id": "x"}, timeout=15)
    assert r.status_code in (401, 403)


def test_analyse_bad_file(auth):
    r = requests.post(
        f"{API}/tacho/analyse",
        headers=auth,
        json={"file_id": "does_not_exist"},
        timeout=30,
    )
    assert r.status_code == 404


def test_list_analyses_requires_auth():
    r = requests.get(f"{API}/tacho/analyses", timeout=15)
    assert r.status_code in (401, 403)
