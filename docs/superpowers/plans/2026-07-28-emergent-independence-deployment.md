# HaulCheck Emergent-Independence & Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HaulCheck run entirely on infrastructure the client controls, deployed to Vercel (frontend) and Render (backend) with MongoDB Atlas, Cloudflare R2 and Resend, at £0/month.

**Architecture:** The `backend/providers/` layer already abstracts AI, storage and email behind environment-selected implementations. This plan finishes the one unimplemented provider (`S3Storage`, for Cloudflare R2), makes the dependency manifests installable off-platform, removes third-party code that phones home from the browser, adds container and platform config, and replaces the sleeping free tier's in-process scheduler with an external cron trigger.

**Tech Stack:** FastAPI · Python 3.12 · MongoDB (motor) · React 19 (CRA + CRACO) · Docker · Render · Vercel · Cloudflare R2 · Resend

## Global Constraints

- All work happens inside ``. The repository layout does **not** change.
- Run backend commands from `backend/`, frontend commands from `frontend/`.
- **Never modify `addopts` in `backend/pytest.ini`.** Run tests serially with `pytest -n 0` (NOT `-p no:xdist`, which errors).
- **No `boto3`.** It is synchronous; calling it from an `async def` handler blocks the event loop. `backend/tests/test_provider_decoupling.py::test_no_vendor_sdk_imported_outside_the_provider_package` fails the build if it appears. All outbound HTTP uses `httpx.AsyncClient`.
- **No `requests` in `backend/*.py` or `backend/providers/*.py`.** Same guard, same reason. It remains allowed in `backend/tests/`.
- Vendor SDK names may appear **only** inside `backend/providers/{ai,email,storage}.py`. `server.py` must not read `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `RESEND_API_KEY`, `ANTHROPIC_API_KEY` or `EMERGENT_LLM_KEY` directly.
- Every collection query stays scoped by `org_id`. `test_tenancy_guard.py` fails the build otherwise.
- Every interactive or informational frontend element needs a `data-testid`.
- AI ships **disabled** (`AI_PROVIDER=null`). Do not enable it.
- Google sign-in ships **disabled** (`GOOGLE_CLIENT_ID` unset). Do not enable it.
- Preserve the DO-NOT-EDIT header block in `test_result.md`, and leave `test_reports/` in place.
- Commit after every task. Branch is `saas-conversion`.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `backend/providers/_sigv4.py` | AWS Signature V4 request signing. Pure functions, no I/O, no vendor SDK. |
| `backend/tests/test_sigv4.py` | Signing correctness, verified differentially against botocore. |
| `backend/tests/test_s3_storage.py` | `S3Storage` behaviour; live round trip gated on `S3_*` env vars. |
| `backend/tests/test_no_third_party_frontend.py` | Static guard: nothing in the browser bundle calls a host the client does not own. |
| `backend/tests/test_cron_endpoint.py` | The reminder-trigger endpoint rejects bad secrets. |
| `backend/requirements-dev.txt` | Test and lint tooling, kept out of the production image. |
| `backend/Dockerfile` | Production container. |
| `backend/.dockerignore` | Keeps the build context small. |
| `render.yaml` | Render blueprint at repo root. |
| `frontend/vercel.json` | SPA rewrite so React Router deep links resolve. |
| `DEPLOYMENT.md` | The operator guide, at repo root. |

**Modified:**

| Path | Change |
|---|---|
| `backend/providers/storage.py:96-131` | Replace the `S3Storage` stub with a working implementation. |
| `backend/requirements.txt` | Rewrite. Currently unusable off-platform. |
| `backend/server.py:4754-4781` | Reminder jobs return counts instead of `None`. |
| `backend/server.py` (new route) | `POST /api/tasks/run-reminders`. |
| `backend/.env.example` | Document `CRON_SECRET`, `TRUST_PROXY_HEADERS` for Render. |
| `frontend/public/index.html` | Remove the Emergent script and the PostHog snippet; fix the canonical URL. |
| `frontend/public/robots.txt`, `sitemap.xml` | Remove Emergent host. |
| `frontend/package.json` | Remove `@emergentbase/visual-edits`; pin `engines.node`. |
| `frontend/craco.config.js:131-145` | Remove the visual-edits wrapper. |
| `frontend/.env.example` | Note the production value shape. |

**Deleted:** `.emergent/`, `.gitconfig`

---

## Task 1: Remove third-party code from the browser bundle

The frontend currently loads two scripts the client does not control: Emergent's `emergent-main.js`, and a PostHog snippet with **session recording enabled**, keyed to an analytics project that is not the client's. HaulCheck screens display driver licence numbers, CPC and tachograph records, so session replay of them is a data-protection problem as well as an independence one.

**Files:**
- Create: `backend/tests/test_no_third_party_frontend.py`
- Modify: `frontend/public/index.html`, `frontend/public/robots.txt`, `frontend/public/sitemap.xml`, `frontend/package.json`, `frontend/craco.config.js`
- Delete: `.emergent/`, `.gitconfig`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. Later tasks rely only on `@emergentbase/visual-edits` being absent from `package.json`.

- [ ] **Step 1: Write the failing guard test**

Create `backend/tests/test_no_third_party_frontend.py`:

```python
"""Static guard: the browser bundle talks only to hosts the client owns.

Anything loaded here runs inside a compliance product that displays driver
licence numbers, CPC status and tachograph records. A third-party script is not
just a dependency -- it is an unaudited party with read access to that screen,
and under GDPR it is the client's disclosure to justify.

This reads source rather than behaviour: detecting it at runtime would mean
loading the page against a real analytics account to find out it was leaking.
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"

# Hosts belonging to the platform being migrated away from, plus the analytics
# vendor whose key was baked into index.html.
FORBIDDEN = re.compile(
    r"emergentagent\.com|emergent\.sh|emergent\.host|emergentbase|posthog",
    re.IGNORECASE,
)

SCANNED_DIRS = (FRONTEND / "public", FRONTEND / "src")
SCANNED_SUFFIXES = {".html", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt", ".xml", ".css"}


def _scanned_files():
    for root in SCANNED_DIRS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SCANNED_SUFFIXES:
                yield path
    for name in ("package.json", "craco.config.js"):
        candidate = FRONTEND / name
        if candidate.exists():
            yield candidate


def test_no_third_party_host_in_the_frontend():
    violations = []
    for path in _scanned_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        for match in FORBIDDEN.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            violations.append(
                f"  {path.relative_to(FRONTEND)}:{line}  references `{match.group(0)}`")

    assert not violations, (
        "The frontend references a host the client does not control.\n\n"
        "Scripts loaded in the browser can read every field on the page, which\n"
        "here includes driver licence and tachograph data. Remove the reference,\n"
        "or self-host the asset.\n\n" + "\n".join(sorted(violations))
    )


def test_emergent_platform_files_are_gone():
    repo = BACKEND.parent.parent.parent
    leftovers = [str(p.relative_to(repo)) for p in
                 (repo / ".emergent",
                  repo / ".gitconfig") if p.exists()]
    assert not leftovers, (
        "Emergent platform files remain: " + ", ".join(leftovers) + "\n"
        ".gitconfig sets the commit author to github@emergent.sh; .emergent/ "
        "pins a platform image that no longer exists for this deployment."
    )
```

- [ ] **Step 2: Run it and confirm both tests fail**

```bash
cd "backend"
pytest tests/test_no_third_party_frontend.py -n 0 -v
```

Expected: both FAIL. The first lists `index.html` (Emergent script, PostHog snippet, canonical URL), `robots.txt`, `sitemap.xml`, `package.json` and `craco.config.js`. The second lists `.emergent` and `.gitconfig`.

- [ ] **Step 3: Strip the third-party scripts from `index.html`**

In `frontend/public/index.html`:

Delete this line entirely (it is the whole Emergent loader):

```html
<script src="https://assets.emergent.sh/scripts/emergent-main.js"></script>
```

Delete the **entire** `<script>` block near the end of `<body>` that begins `!(function (t, e) {` and ends with the `posthog.init(...)` call and `</script>`. Remove the whole block including both tags — leaving a partial snippet is worse than leaving all of it.

Replace the canonical link:

```html
<link rel="canonical" href="https://transport-verify-3.emergent.host/" />
```

with a comment, because the production domain is not known yet and a wrong canonical actively tells search engines the app lives somewhere else:

```html
<!-- Set once the production domain is live: <link rel="canonical" href="https://app.example.com/" /> -->
```

Keep the `DataCloneError` suppression script, the meta tags, the title and the Google Fonts links — none of those are in scope.

- [ ] **Step 4: Remove the Emergent host from `robots.txt` and `sitemap.xml`**

In `frontend/public/robots.txt`, replace the last line:

```
Sitemap: https://transport-verify-3.emergent.host/sitemap.xml
```

with:

```
# Sitemap: https://app.example.com/sitemap.xml
```

Replace the whole of `frontend/public/sitemap.xml` with a relative-free placeholder that carries no host:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!--
  Absolute URLs are required by the sitemap protocol, so this file cannot be
  completed until the production domain exists. Fill both <loc> values in and
  uncomment the Sitemap line in robots.txt at that point.
-->
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
</urlset>
```

- [ ] **Step 5: Remove the visual-edits package and pin Node**

In `frontend/package.json`, delete the dependency line:

```json
"@emergentbase/visual-edits": "https://assets.emergent.sh/npm/emergentbase-visual-edits-1.0.13.tgz",
```

Add an `engines` block as a sibling of `"scripts"` — Vercel otherwise picks whatever its current default Node is, and that will drift under you:

```json
  "engines": {
    "node": "20.x"
  },
```

- [ ] **Step 6: Remove the visual-edits wrapper from CRACO**

In `frontend/craco.config.js`, delete lines 131-145 — the whole `if (isDevServer) { try { ... } catch (err) { ... } }` block that requires `@emergentbase/visual-edits/craco`.

`isDevServer` (line 7) becomes unused. Delete its declaration too, and the now-stale comment above it.

- [ ] **Step 7: Delete the platform files**

```bash
cd "."
git rm -r --cached .emergent
rm -rf .emergent
git rm --cached .gitconfig
rm -f .gitconfig
```

- [ ] **Step 8: Run the guard and confirm both tests pass**

```bash
cd "backend"
pytest tests/test_no_third_party_frontend.py -n 0 -v
```

Expected: 2 passed.

- [ ] **Step 9: Confirm the frontend still builds without the removed package**

```bash
cd "frontend"
yarn install
yarn build
```

Expected: build completes. The `[visual-edits] ... not installed` warning must **not** appear — that code is gone, not merely inert.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Remove third-party scripts from the browser bundle

index.html loaded Emergent's emergent-main.js and a PostHog snippet with
session recording enabled, keyed to an analytics project the client does not
own. HaulCheck screens show driver licence, CPC and tachograph data, so
replaying those sessions to a third party is a disclosure problem as well as a
coupling one.

Also drops the visual-edits package (served from assets.emergent.sh, so an
install would break if that host went away), clears the canonical URL and
sitemap that pointed at the Emergent host, and deletes .emergent/ and the
.gitconfig that set the commit author to github@emergent.sh.

A static guard fails the build if any of it comes back."
```

---

## Task 2: AWS Signature V4 signer

`S3Storage` needs signed requests. boto3 would do this but is synchronous — the reason `providers/storage.py` was rewritten around `httpx` in the first place. This task builds the signing as pure functions with no I/O, so it can be tested exhaustively offline.

**Files:**
- Create: `backend/providers/_sigv4.py`, `backend/tests/test_sigv4.py`
- Modify: `backend/requirements-dev.txt` (created in this task; superseded by Task 4's full version)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_sigv4.sign(*, method: str, url: str, headers: dict, payload: bytes, access_key: str, secret_key: str, region: str, service: str = "s3", now: datetime | None = None) -> dict[str, str]` — returns a **new** dict: the input headers plus `host`, `x-amz-date`, `x-amz-content-sha256` and `Authorization`. Does not mutate the input.
  - `_sigv4.signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes`
  - `_sigv4.EMPTY_SHA256: str`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sigv4.py`. The core test compares our output against **botocore**, the reference implementation, rather than hard-coded hashes — a constant typed from memory that happens to be wrong would send the next engineer hunting a bug that is not there.

```python
"""SigV4 correctness, checked against botocore's reference implementation.

botocore is a *test* dependency only. Importing boto3/botocore in application
code is blocked by test_provider_decoupling.py, because it is synchronous and
would block the event loop from an async handler. Here it never runs in a
request path -- it only tells us whether our own signing agrees with the
implementation AWS ships.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import _sigv4  # noqa: E402

FROZEN = dt.datetime(2026, 7, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
ACCESS = "AKIDEXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
ENDPOINT = "https://acct123.r2.cloudflarestorage.com"


def _ours(method, url, payload, headers=None):
    return _sigv4.sign(
        method=method, url=url, headers=headers or {}, payload=payload,
        access_key=ACCESS, secret_key=SECRET, region="auto", service="s3",
        now=FROZEN)


def _botocore_authorization(method, url, payload, headers=None):
    """The same request signed by botocore, for comparison."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    stamp = FROZEN.strftime("%Y%m%dT%H%M%SZ")
    hdrs = dict(headers or {})
    hdrs["X-Amz-Date"] = stamp
    hdrs["X-Amz-Content-SHA256"] = _sigv4.sha256_hex(payload)

    request = AWSRequest(method=method, url=url, data=payload, headers=hdrs)
    request.context["timestamp"] = stamp

    auth = SigV4Auth(Credentials(ACCESS, SECRET), "s3", "auto")
    canonical = auth.canonical_request(request)
    to_sign = auth.string_to_sign(request, canonical)
    signature = auth.signature(to_sign, request)
    signed_headers = auth.signed_headers(auth.headers_to_sign(request))
    return (f"AWS4-HMAC-SHA256 Credential={ACCESS}/{auth.scope(request)}, "
            f"SignedHeaders={signed_headers}, Signature={signature}")


class TestAgreesWithBotocore:
    """If these diverge, R2 returns SignatureDoesNotMatch and nothing uploads."""

    def setup_method(self):
        pytest.importorskip(
            "botocore",
            reason="botocore is a dev dependency: pip install -r requirements-dev.txt")

    def test_put_with_a_body(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        headers = {"Content-Type": "image/jpeg"}
        payload = b"binary-evidence-bytes"
        assert (_ours("PUT", url, payload, headers)["Authorization"]
                == _botocore_authorization("PUT", url, payload, headers))

    def test_get_with_an_empty_body(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        assert (_ours("GET", url, b"")["Authorization"]
                == _botocore_authorization("GET", url, b""))

    def test_key_containing_characters_that_need_encoding(self):
        # Uploaded filenames reach the key unmodified, so spaces and
        # parentheses are routine. Encoding them differently from botocore is
        # the classic SigV4 bug.
        url = f"{ENDPOINT}/haulcheck/walkaround/sheet%20%281%29.pdf"
        assert (_ours("GET", url, b"")["Authorization"]
                == _botocore_authorization("GET", url, b""))

    def test_delete(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        assert (_ours("DELETE", url, b"")["Authorization"]
                == _botocore_authorization("DELETE", url, b""))


class TestSignedHeaders:
    def test_required_headers_are_added(self):
        signed = _ours("GET", f"{ENDPOINT}/haulcheck/x", b"")
        assert signed["host"] == "acct123.r2.cloudflarestorage.com"
        assert signed["x-amz-date"] == "20260728T120000Z"
        assert signed["x-amz-content-sha256"] == _sigv4.EMPTY_SHA256
        assert signed["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=")

    def test_the_caller_s_headers_are_not_mutated(self):
        original = {"Content-Type": "image/jpeg"}
        _ours("PUT", f"{ENDPOINT}/haulcheck/x", b"data", original)
        assert original == {"Content-Type": "image/jpeg"}

    def test_empty_payload_hash_is_the_sha256_of_no_bytes(self):
        assert _sigv4.EMPTY_SHA256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_signing_key_is_deterministic(self):
        a = _sigv4.signing_key(SECRET, "20260728", "auto", "s3")
        b = _sigv4.signing_key(SECRET, "20260728", "auto", "s3")
        assert a == b and len(a) == 32
```

- [ ] **Step 2: Add botocore as a dev dependency**

Create `backend/requirements-dev.txt`:

```
# Test and lint tooling. NOT installed in the production image -- see Dockerfile.
-r requirements.txt

pytest==8.3.3
pytest-xdist==3.6.1
requests==2.32.3

# Reference SigV4 implementation, used only to verify providers/_sigv4.py in
# tests/test_sigv4.py. It must never be imported by application code: botocore
# is synchronous and would block the event loop from an async handler.
botocore==1.34.162
```

Install it:

```bash
cd "backend"
pip install botocore==1.34.162
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_sigv4.py -n 0 -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'providers._sigv4'`.

- [ ] **Step 4: Implement the signer**

Create `backend/providers/_sigv4.py`:

```python
"""AWS Signature Version 4, for the S3 REST API.

boto3 implements this already, and is not used here for the reason given in
`storage.py`: it is synchronous, and one blocking call inside an `async def`
handler stalls every other request the process is serving. Signing is a pure
function of the request, so implementing it costs less than the alternative and
is exhaustively testable without a network.

Verified against botocore in `tests/test_sigv4.py`. Any change here must keep
that test passing -- a signature that is merely *plausible* produces
`SignatureDoesNotMatch` from the storage provider and no uploads at all.

Reference: https://docs.aws.amazon.com/IAM/latest/UserGuide/create-signed-request.html
"""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"

# SHA-256 of zero bytes. Required as `x-amz-content-sha256` on bodyless
# requests; S3 rejects the request without it.
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the request-scoped signing key.

    Scoped by date, region and service so a leaked signature cannot be replayed
    against another day, region or service.
    """
    k_date = _hmac(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def _canonical_uri(path: str) -> str:
    """Percent-encode the path, keeping `/` as the separator.

    S3 does *not* double-encode the path, unlike most other AWS services. `~` is
    unreserved and must be left alone.
    """
    return quote(path, safe="/~") or "/"


def _canonical_query(query: str) -> str:
    """Sort and encode query parameters, as the canonical request requires."""
    if not query:
        return ""
    pairs = []
    for part in query.split("&"):
        name, _, value = part.partition("=")
        pairs.append((quote(name, safe="~"), quote(value, safe="~")))
    pairs.sort()
    return "&".join(f"{name}={value}" for name, value in pairs)


def sign(*, method: str, url: str, headers: Dict[str, str], payload: bytes,
         access_key: str, secret_key: str, region: str, service: str = "s3",
         now: Optional[datetime] = None) -> Dict[str, str]:
    """Return a new header dict carrying the SigV4 `Authorization` header.

    The caller's `headers` are copied, never mutated -- callers reuse their
    header dict across retries.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parts = urlsplit(url)
    payload_hash = sha256_hex(payload or b"")

    signed: Dict[str, str] = dict(headers)
    signed["host"] = parts.netloc
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_hash

    # Canonical headers are lowercase, whitespace-collapsed and name-sorted.
    canonical_pairs = sorted(
        (name.lower(), " ".join(str(value).split())) for name, value in signed.items())
    canonical_headers = "".join(f"{name}:{value}\n" for name, value in canonical_pairs)
    signed_header_names = ";".join(name for name, _ in canonical_pairs)

    canonical_request = "\n".join([
        method.upper(),
        _canonical_uri(parts.path),
        _canonical_query(parts.query),
        canonical_headers,
        signed_header_names,
        payload_hash,
    ])

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        ALGORITHM, amz_date, scope, sha256_hex(canonical_request.encode("utf-8"))])

    signature = hmac.new(
        signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    signed["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_header_names}, Signature={signature}")
    return signed
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_sigv4.py -n 0 -v
```

Expected: all PASS. If `TestAgreesWithBotocore` fails, the diff between the two `Authorization` values tells you which component disagrees — print `canonical_request` from both sides before changing anything.

- [ ] **Step 6: Confirm the decoupling guard still passes**

`_sigv4.py` lives in `providers/`, so it is inside the allow-list — but confirm nothing regressed:

```bash
pytest tests/test_provider_decoupling.py -n 0 -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/providers/_sigv4.py backend/tests/test_sigv4.py backend/requirements-dev.txt
git commit -m "Add SigV4 request signing for S3-compatible storage

Signing is a pure function of the request, so it is implemented directly rather
than pulling in boto3 -- which is synchronous, and would reintroduce the
event-loop blocking that providers/storage.py was rewritten to remove.

Correctness is checked differentially against botocore rather than against
hard-coded digests, so the test cannot pass because a constant was mistyped
consistently in two places. botocore is a dev dependency only."
```

---

## Task 3: Implement `S3Storage` against Cloudflare R2

`S3Storage` is a stub whose methods raise `NotImplementedError`. Until this lands, every upload fails the moment the app leaves Emergent — defect photos, signed walkaround sheets and insurance certificates all go through it.

**Files:**
- Modify: `backend/providers/storage.py:96-131`
- Create: `backend/tests/test_s3_storage.py`

**Interfaces:**
- Consumes: `_sigv4.sign(...)` from Task 2.
- Produces: `S3Storage` satisfying the existing `StorageProvider` interface — `async put(path, data, content_type) -> dict` (the dict must contain `"path"`), `async get(path) -> tuple[bytes, str]`, `async delete(path) -> None`, `async healthy() -> bool`. `get_provider()` already constructs it when `STORAGE_PROVIDER=s3`; that wiring does not change.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_s3_storage.py`:

```python
"""S3Storage against an S3-compatible endpoint (Cloudflare R2).

The round-trip tests need a real bucket, so they are skipped unless the S3_*
variables are set. The rest run everywhere: they cover URL construction and
error translation, which is where the bugs that reach production actually live
-- a signing error is loud, a path built wrong is silent until someone cannot
find their evidence.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import storage as storage_module  # noqa: E402

LIVE = all(os.environ.get(k) for k in
           ("S3_BUCKET", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"))
requires_bucket = pytest.mark.skipif(
    not LIVE, reason="Set S3_BUCKET/S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY to run")


def _provider():
    return storage_module.S3Storage(
        bucket="haulcheck", endpoint="https://acct123.r2.cloudflarestorage.com",
        access_key="AKIDEXAMPLE", secret_key="secret", region="auto")


class TestUrlConstruction:
    """R2 uses path-style addressing: <endpoint>/<bucket>/<key>."""

    def test_key_is_appended_to_bucket(self):
        assert _provider()._url("defects/photo.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/defects/photo.jpg")

    def test_a_leading_slash_on_the_key_does_not_double_up(self):
        assert _provider()._url("/defects/photo.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/defects/photo.jpg")

    def test_a_trailing_slash_on_the_endpoint_does_not_double_up(self):
        provider = storage_module.S3Storage(
            bucket="haulcheck", endpoint="https://acct123.r2.cloudflarestorage.com/",
            access_key="k", secret_key="s")
        assert provider._url("a.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/a.jpg")


class TestConfiguration:
    def test_region_defaults_to_auto(self):
        # R2 rejects any other region.
        provider = storage_module.S3Storage(
            bucket="b", endpoint="https://e", access_key="k", secret_key="s")
        assert provider.region == "auto"

    def test_an_empty_region_becomes_auto(self):
        provider = storage_module.S3Storage(
            bucket="b", endpoint="https://e", access_key="k", secret_key="s", region="")
        assert provider.region == "auto"

    def test_the_stub_is_gone(self):
        assert not hasattr(storage_module.S3Storage, "_unimplemented"), (
            "S3Storage._unimplemented is a leftover from the stub")


@requires_bucket
class TestRoundTripAgainstARealBucket:
    @pytest.mark.asyncio
    async def test_put_then_get_returns_the_same_bytes(self):
        provider = storage_module.get_provider()
        key = f"tests/{uuid.uuid4().hex}.txt"
        payload = b"walkaround-sheet-bytes"
        meta = await provider.put(key, payload, "text/plain")
        assert meta["path"] == key
        data, content_type = await provider.get(key)
        assert data == payload
        assert content_type.startswith("text/plain")
        await provider.delete(key)

    @pytest.mark.asyncio
    async def test_get_after_delete_reports_it_is_missing(self):
        provider = storage_module.get_provider()
        key = f"tests/{uuid.uuid4().hex}.txt"
        await provider.put(key, b"x", "text/plain")
        await provider.delete(key)
        with pytest.raises(storage_module.StorageUnavailable):
            await provider.get(key)

    @pytest.mark.asyncio
    async def test_healthy_is_true_for_a_reachable_bucket(self):
        assert await storage_module.get_provider().healthy() is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_s3_storage.py -n 0 -v
```

Expected: `TestUrlConstruction` fails with `AttributeError: 'S3Storage' object has no attribute '_url'`; `test_the_stub_is_gone` fails; the round-trip class is skipped.

- [ ] **Step 3: Replace the `S3Storage` stub**

In `backend/providers/storage.py`, replace the whole class body from line 96 (`class S3Storage(StorageProvider):`) through line 130 (the end of `_unimplemented`) with:

```python
class S3Storage(StorageProvider):
    """S3-compatible storage (Cloudflare R2, AWS S3, MinIO, Backblaze B2).

    Implemented against the S3 REST API through httpx rather than boto3, which
    is synchronous and would reintroduce the blocking this module exists to fix.
    Requests are signed by `_sigv4`, which is verified against botocore in
    `tests/test_sigv4.py`.

    Addressing is path-style (`<endpoint>/<bucket>/<key>`) because R2 does not
    serve virtual-host style on the default endpoint.
    """

    name = "s3"

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str,
                 region: str = "auto"):
        self.bucket = bucket
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        # R2 accepts only "auto"; an empty value here would sign a scope the
        # server rejects with an error that does not mention the region.
        self.region = region or "auto"

    def _url(self, path: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{path.lstrip('/')}"

    async def _send(self, method: str, path: str, *, data: bytes = b"",
                    content_type: str = "", timeout: int = 120):
        url = self._url(path)
        headers = {"Content-Type": content_type} if content_type else {}
        headers = _sigv4.sign(
            method=method, url=url, headers=headers, payload=data,
            access_key=self.access_key, secret_key=self.secret_key,
            region=self.region, service="s3")
        async with httpx.AsyncClient(timeout=timeout) as http:
            return await http.request(method, url, headers=headers,
                                      content=data or None)

    @staticmethod
    def _fail(action: str, path: str, response) -> StorageUnavailable:
        # S3 returns the reason in an XML body. Including a slice of it turns
        # "upload failed" into something diagnosable -- SignatureDoesNotMatch
        # and NoSuchBucket are different problems with different fixes.
        return StorageUnavailable(
            f"Storage {action} failed for '{path}': HTTP {response.status_code}. "
            f"{response.text[:300]}")

    async def put(self, path: str, data: bytes, content_type: str) -> dict:
        response = await self._send("PUT", path, data=data, content_type=content_type)
        if response.status_code >= 400:
            raise self._fail("upload", path, response)
        return {
            "path": path,
            "size": len(data),
            "content_type": content_type,
            "etag": response.headers.get("ETag", "").strip('"'),
        }

    async def get(self, path: str) -> Tuple[bytes, str]:
        response = await self._send("GET", path, timeout=60)
        if response.status_code == 404:
            raise StorageUnavailable(f"No stored object at '{path}'.")
        if response.status_code >= 400:
            raise self._fail("download", path, response)
        return response.content, response.headers.get(
            "Content-Type", "application/octet-stream")

    async def delete(self, path: str) -> None:
        response = await self._send("DELETE", path, timeout=60)
        # 404 is success for a delete: the object is not there, which is the
        # requested end state.
        if response.status_code not in (200, 202, 204, 404):
            raise self._fail("delete", path, response)

    async def healthy(self) -> bool:
        """True when the bucket exists and these credentials can reach it."""
        try:
            response = await self._send("HEAD", "", timeout=15)
            return response.status_code < 400
        except Exception as e:
            logging.error(f"S3 storage health check failed: {e}")
            return False
```

Note `healthy()` signs `HEAD <endpoint>/<bucket>/` — a bucket-level HEAD. `_url("")` yields a trailing slash, which is the correct canonical path for that request.

- [ ] **Step 4: Add the import**

At the top of `backend/providers/storage.py`, below `import httpx`, add:

```python
from . import _sigv4
```

- [ ] **Step 5: Add pytest-asyncio for the async tests**

The round-trip tests use `@pytest.mark.asyncio`. Add to `backend/requirements-dev.txt`:

```
pytest-asyncio==0.24.0
```

Install and register the mode. Append to `backend/pytest.ini` — **add only the `asyncio_mode` line; do not touch `addopts`**:

```ini
asyncio_mode = auto
```

```bash
pip install pytest-asyncio==0.24.0
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_s3_storage.py tests/test_sigv4.py -n 0 -v
```

Expected: `TestUrlConstruction` and `TestConfiguration` PASS; the round-trip class is SKIPPED (no bucket configured yet — it runs in Task 8's smoke test).

- [ ] **Step 7: Confirm nothing else regressed**

```bash
pytest tests/test_provider_decoupling.py tests/test_no_third_party_frontend.py -n 0 -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/providers/storage.py backend/tests/test_s3_storage.py backend/requirements-dev.txt backend/pytest.ini
git commit -m "Implement S3Storage for Cloudflare R2

The class was a stub whose methods raised NotImplementedError, so every upload
would have failed the moment the app left Emergent's object store -- defect
photos, signed walkaround sheets and insurance certificates all route through
it.

Path-style addressing, because R2 does not serve virtual-host style on the
default endpoint, and region is forced to 'auto', which is the only value R2
accepts. Errors carry a slice of the S3 XML body: SignatureDoesNotMatch and
NoSuchBucket need different fixes and 'upload failed' distinguishes neither.

Round-trip tests skip unless a bucket is configured; URL construction and
error translation are covered everywhere."
```

---

## Task 4: A `requirements.txt` that installs off-platform

`backend/requirements.txt` is the Emergent *image* manifest, not this application's dependency list. Line 23 pins `emergentintegrations==0.2.0`, which is not published on PyPI, and line 58 pulls litellm from `customer-assets.emergentagent.com`. A Render build fails on both. It also carries roughly forty packages the app never imports.

`requirements-local.txt` is the honest list — it was written to be the minimum that actually runs the app — but it is missing `dnspython`, without which MongoDB Atlas `mongodb+srv://` URIs fail to resolve with an error that does not mention DNS.

**Files:**
- Modify: `backend/requirements.txt` (full rewrite), `backend/requirements-dev.txt`
- Delete: `backend/requirements-local.txt`
- Create: `backend/tests/test_requirements.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `requirements.txt` installable on any PyPI-connected host. Task 6's Dockerfile depends on it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_requirements.py`:

```python
"""The dependency manifest must install somewhere other than the machine that
wrote it.

The original requirements.txt named a package that is not on PyPI and a wheel
served from the platform's own asset host. Both install fine inside that
platform's image and fail everywhere else -- and they fail at *build* time on a
deploy host, which is the worst moment to discover it.
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REQUIREMENTS = BACKEND / "requirements.txt"


def _requirement_lines():
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            yield line


def test_no_dependency_is_fetched_from_a_url():
    """A URL pin ties the build to one host staying up and serving that file."""
    offenders = [line for line in _requirement_lines()
                 if re.search(r"https?://|@\s*http|git\+", line)]
    assert not offenders, (
        "requirements.txt fetches a dependency from a URL:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse a PyPI release, or vendor the code into the repository."
    )


def test_no_dependency_is_unavailable_outside_the_platform():
    banned = ("emergentintegrations",)
    offenders = [line for line in _requirement_lines()
                 if any(name in line.lower() for name in banned)]
    assert not offenders, (
        "requirements.txt names a package that is not published on PyPI:\n  "
        + "\n  ".join(offenders)
        + "\n\nAI runs through providers/ai.py, which imports it lazily. With "
          "AI_PROVIDER=null it is never reached and must not be a build dependency."
    )


def test_dnspython_is_present_for_atlas_srv_uris():
    """MongoDB Atlas hands out mongodb+srv:// URIs, which need dnspython.

    Without it pymongo raises a configuration error that never mentions DNS, so
    the failure reads like a bad password.
    """
    assert any(line.lower().startswith("dnspython") for line in _requirement_lines()), (
        "dnspython is missing. MONGO_URL from Atlas begins mongodb+srv:// and "
        "cannot be resolved without it."
    )


def test_test_tooling_is_not_in_the_production_manifest():
    tooling = ("pytest", "black", "flake8", "mypy", "isort", "botocore", "boto3")
    offenders = [line for line in _requirement_lines()
                 if any(line.lower().startswith(name) for name in tooling)]
    assert not offenders, (
        "Test/lint tooling belongs in requirements-dev.txt, not the production "
        "image:\n  " + "\n  ".join(offenders)
    )


def test_requirements_local_has_been_folded_in():
    assert not (BACKEND / "requirements-local.txt").exists(), (
        "requirements-local.txt existed because requirements.txt could not be "
        "installed off-platform. Now that it can, two manifests will drift."
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_requirements.py -n 0 -v
```

Expected: all five FAIL.

- [ ] **Step 3: Rewrite `requirements.txt`**

Replace the entire contents of `backend/requirements.txt` with:

```
# Production dependencies.
#
# Every package here is on PyPI and installs on any host. The previous version
# of this file was the Emergent platform image manifest: it named
# `emergentintegrations` (never published) and fetched litellm from
# customer-assets.emergentagent.com, so `pip install -r requirements.txt`
# succeeded only inside that image.
#
# Test and lint tooling lives in requirements-dev.txt so it stays out of the
# production container.
#
#   pip install -r requirements.txt

# --- Web framework ---
fastapi==0.110.1
uvicorn[standard]==0.25.0
starlette==0.37.2
python-multipart==0.0.9

# --- Data / validation ---
pydantic==2.9.2
email-validator==2.2.0
python-dotenv==1.0.1

# --- Database ---
motor==3.5.1
pymongo==4.8.0
# Required for MongoDB Atlas: its connection strings use the mongodb+srv://
# scheme, which resolves through a DNS SRV lookup. Without this, pymongo fails
# with an error that does not mention DNS.
dnspython==2.8.0

# --- Auth ---
PyJWT==2.9.0
passlib==1.7.4
bcrypt==4.1.3

# --- HTTP client ---
# httpx only. `requests` is synchronous and blocks the event loop when called
# from an async handler; tests/test_provider_decoupling.py enforces this.
httpx==0.27.2

# --- PDF generation (imported at module scope by pdf_export.py) ---
reportlab==4.2.5
pypdf==5.1.0
pillow==10.4.0

# --- Scheduler ---
APScheduler==3.10.4

# --- Email (providers/email.py) ---
resend==2.32.2

# --- AI ---
# Deliberately absent. The app ships with AI_PROVIDER=null and every AI call
# site already degrades. To enable it, add `anthropic` here, set
# AI_PROVIDER=anthropic and ANTHROPIC_API_KEY, and redeploy. Until then
# providers/ai.py never imports it -- the import is inside chat().
```

- [ ] **Step 4: Finalise `requirements-dev.txt`**

Replace `backend/requirements-dev.txt` with:

```
# Test and lint tooling. Not installed in the production image -- see Dockerfile.
#
#   pip install -r requirements-dev.txt

-r requirements.txt

# --- Tests ---
pytest==8.3.3
pytest-xdist==3.6.1
pytest-asyncio==0.24.0

# The backend suite is integration-style: it drives a live API over HTTP.
# `requests` is fine here because it never runs inside the event loop.
requests==2.32.3

# Reference SigV4 implementation, used only to verify providers/_sigv4.py.
# Must never be imported by application code -- it is synchronous.
botocore==1.34.162
```

- [ ] **Step 5: Delete the superseded manifest**

```bash
cd "backend"
git rm requirements-local.txt
```

- [ ] **Step 6: Verify nothing imports a removed package**

```bash
cd "backend"
grep -rnE "^\s*(import|from)\s+(pandas|boto3|litellm|openai|tiktoken|tokenizers|huggingface_hub|google\.|googleapiclient|stripe|numpy)\b" \
  --include=*.py . | grep -v "/tests/"
```

Expected: **no output**. Any hit must be resolved before continuing — either the import is dead code to delete, or the package belongs back in `requirements.txt`.

- [ ] **Step 7: Verify a clean install works**

```bash
cd "backend"
python -m venv /tmp/hc-verify
/tmp/hc-verify/bin/pip install -r requirements.txt
/tmp/hc-verify/bin/python -c "import server" 2>&1 | tail -5
```

On Windows use `\tmp\hc-verify\Scripts\pip` and `...\python`.

Expected: the install completes with no URL fetches. `import server` will fail on missing env vars (`MONGO_URL` is read at module scope) — that is expected and fine. It must **not** fail with `ModuleNotFoundError`.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
pytest tests/test_requirements.py -n 0 -v
```

Expected: 5 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt
git commit -m "Make requirements.txt installable off the Emergent image

It was the platform image manifest, not this app's dependency list: it named
emergentintegrations, which is not published on PyPI, and fetched litellm from
customer-assets.emergentagent.com. Both resolve only inside that image, so any
other host fails at build time.

Rebuilt from requirements-local.txt -- written as the minimum that actually
runs the app -- with resend added, test tooling split into requirements-dev.txt,
and roughly forty unused packages dropped.

Adds dnspython, which Atlas needs for mongodb+srv:// and whose absence
surfaces as an error that never mentions DNS."
```

---

## Task 5: External trigger for the reminder jobs

Render's free tier stops the instance after 15 minutes idle, so the in-process APScheduler never reaches 07:00 and no compliance reminder is ever sent. An external scheduler calls this endpoint instead, which also wakes the instance.

**Files:**
- Modify: `backend/server.py:4754-4781` (return counts), `backend/server.py` (new route near the reminder jobs), `backend/.env.example`
- Create: `backend/tests/test_cron_endpoint.py`

**Interfaces:**
- Consumes: `scheduling.run_once` (already applied to both jobs), `security.client_ip`, `security.record_failure`.
- Produces: `POST /api/tasks/run-reminders`, optional query `?job=daily|weekly`. Auth: `Authorization: Bearer <CRON_SECRET>`. Returns `{"ran": {"daily": {...} | None, "weekly": {...} | None}}` — a `null` value means another instance held the lock and this call correctly did nothing.
- `run_daily_reminders()` and `run_weekly_reminders()` now return `dict` (`{"orgs": int, "sent": int, "failed": int}`) instead of `None`. `run_once` passes the return value through and yields `None` when the lock is held.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cron_endpoint.py`:

```python
"""The reminder-trigger endpoint.

On a free-tier host the instance sleeps, so the in-process scheduler never
reaches 07:00 and no reminder is ever sent. An external cron calls this instead.

That makes it a publicly reachable route that sends email to every customer, so
the interesting tests are the ones about refusing to run it.
"""
import os

import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
URL = f"{BASE}/api/tasks/run-reminders"
SECRET = os.environ.get("CRON_SECRET", "")


class TestAuthorisation:
    def test_no_authorization_header_is_rejected(self):
        response = requests.post(URL, timeout=30)
        assert response.status_code in (401, 503), response.text

    def test_a_wrong_secret_is_rejected(self):
        response = requests.post(
            URL, headers={"Authorization": "Bearer not-the-secret"}, timeout=30)
        assert response.status_code in (401, 503), response.text

    def test_the_secret_is_not_accepted_as_a_query_parameter(self):
        # Query strings land in access logs and browser history; the secret
        # belongs in a header only.
        response = requests.post(f"{URL}?secret={SECRET or 'x'}", timeout=30)
        assert response.status_code in (401, 503), response.text


class TestTriggering:
    def _auth(self):
        if not SECRET:
            import pytest
            pytest.skip("Set CRON_SECRET to exercise a successful trigger")
        return {"Authorization": f"Bearer {SECRET}"}

    def test_an_unknown_job_name_is_rejected(self):
        response = requests.post(f"{URL}?job=hourly", headers=self._auth(), timeout=60)
        assert response.status_code == 400, response.text

    def test_a_valid_call_reports_what_it_ran(self):
        response = requests.post(f"{URL}?job=daily", headers=self._auth(), timeout=120)
        assert response.status_code == 200, response.text
        assert "daily" in response.json()["ran"]

    def test_a_second_immediate_call_is_skipped_by_the_lock(self):
        """The Mongo job lock is what stops two triggers double-sending."""
        headers = self._auth()
        requests.post(f"{URL}?job=daily", headers=headers, timeout=120)
        second = requests.post(f"{URL}?job=daily", headers=headers, timeout=120)
        assert second.status_code == 200, second.text
        # None means the lock was held, so this call sent nothing.
        assert second.json()["ran"]["daily"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Start the backend in another shell (`uvicorn server:app --reload`), then:

```bash
pytest tests/test_cron_endpoint.py -n 0 -v
```

Expected: FAIL — the route returns 404.

- [ ] **Step 3: Make the reminder jobs return counts**

In `backend/server.py`, replace lines 4754-4781 with:

```python
@scheduling.run_once(lambda: db, "daily_reminders")
async def run_daily_reminders():
    """Returns a summary, or None when another instance held the lock."""
    logger.info("Running daily reminder job")
    summary = {"orgs": 0, "sent": 0, "failed": 0}
    settings_list = await db.reminder_settings.find({"recipients": {"$exists": True, "$ne": []}}, {"_id": 0}).to_list(10000)
    for s in settings_list:
        if not s.get("recipients"):
            continue
        summary["orgs"] += 1
        try:
            res = await _process_daily_user(s["org_id"], s["recipients"])
            if res["new_item_count"]:
                summary["sent"] += 1
                logger.info(f"Daily reminder sent to {s['user_id']} ({res['new_item_count']} new items)")
        except Exception as e:
            summary["failed"] += 1
            logger.error(f"Daily reminder failed for {s.get('user_id')}: {e}")
    return summary


@scheduling.run_once(lambda: db, "weekly_reminders")
async def run_weekly_reminders():
    """Returns a summary, or None when another instance held the lock."""
    logger.info("Running weekly reminder job")
    summary = {"orgs": 0, "sent": 0, "failed": 0}
    settings_list = await db.reminder_settings.find({"recipients": {"$exists": True, "$ne": []}}, {"_id": 0}).to_list(10000)
    for s in settings_list:
        if not s.get("recipients"):
            continue
        summary["orgs"] += 1
        try:
            sent = await _process_weekly_user(s["org_id"], s["recipients"])
            if sent:
                summary["sent"] += 1
                logger.info(f"Weekly summary sent to {s['user_id']} ({sent} recipients)")
        except Exception as e:
            summary["failed"] += 1
            logger.error(f"Weekly reminder failed for {s.get('user_id')}: {e}")
    return summary
```

- [ ] **Step 4: Add the endpoint**

Immediately after `run_weekly_reminders` (before the `@api_router.post("/reminders/send")` route at what was line 4784), insert:

```python
@api_router.post("/tasks/run-reminders")
async def trigger_reminder_jobs(request: Request, job: str = Query("")):
    """Run the reminder jobs on demand, for an external scheduler.

    APScheduler runs these in-process at 07:00 UTC, which works only while the
    process is running. On a host that stops an idle instance, 07:00 arrives
    with nothing listening and the reminders are simply never sent -- silently,
    because no one is awake to log it.

    Both jobs carry `scheduling.run_once`, so triggering one that is already
    running is a no-op rather than a second copy of every customer's email. That
    is what makes this endpoint safe to retry.
    """
    secret = (os.environ.get("CRON_SECRET") or "").strip()
    if not secret:
        # 503 rather than 401: the caller's credentials are not the problem.
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET is not configured, so scheduled jobs cannot be triggered.")

    header = request.headers.get("Authorization", "")
    presented = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not secrets.compare_digest(presented, secret):
        await security.record_failure(db, "login_ip", security.client_ip(request))
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret.")

    requested = (job or "").strip().lower()
    if requested and requested not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="job must be 'daily' or 'weekly'.")

    # With no `job`, do what the in-process schedule would have done today:
    # daily every day, weekly additionally on Mondays. One cron entry, not two.
    is_monday = datetime.now(timezone.utc).weekday() == 0
    ran = {}
    if requested in ("", "daily"):
        ran["daily"] = await run_daily_reminders()
    if requested == "weekly" or (requested == "" and is_monday):
        ran["weekly"] = await run_weekly_reminders()

    logger.info(f"Reminder jobs triggered externally: {ran}")
    return {"ran": ran}
```

`secrets`, `os`, `Request`, `Query`, `datetime`, `timezone`, `security` and `logger` are all already imported in `server.py`. No new imports are needed.

- [ ] **Step 5: Document the new variable**

In `backend/.env.example`, append:

```
# --- Scheduled jobs ---
# APScheduler runs the reminder jobs in-process at 07:00 UTC. That works only
# while the process is running -- on a host that stops an idle instance, 07:00
# arrives with nothing listening and no reminder is sent.
#
# Setting this enables POST /api/tasks/run-reminders, which an external cron
# can call with `Authorization: Bearer <CRON_SECRET>`. Both jobs hold a Mongo
# lock, so an extra call is a no-op rather than duplicate email.
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
# Leave blank and the endpoint returns 503.
CRON_SECRET=
```

- [ ] **Step 6: Run the tests to verify they pass**

Restart the backend, then:

```bash
export CRON_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
# set the same value in backend/.env and restart uvicorn
pytest tests/test_cron_endpoint.py -n 0 -v
```

Expected: all PASS. Without `CRON_SECRET` set, `TestAuthorisation` still passes (503) and `TestTriggering` skips.

- [ ] **Step 7: Confirm the scheduler tests still pass**

```bash
pytest tests/test_scheduling.py -n 0 -v
```

Expected: PASS. The jobs now return a dict where they returned `None`; if a test asserted on `None`, the lock-held path still returns `None` and only the ran path changed.

- [ ] **Step 8: Commit**

```bash
git add backend/server.py backend/.env.example backend/tests/test_cron_endpoint.py
git commit -m "Add an external trigger for the reminder jobs

The in-process scheduler only fires while the process is running. On a host
that stops an idle instance, 07:00 UTC arrives with nothing listening and the
compliance reminders are never sent -- silently, since nothing is awake to log
it.

POST /api/tasks/run-reminders runs them on demand behind a bearer secret. Both
jobs already carry the Mongo run-once lock, so a retry or an overlap with
APScheduler is a no-op rather than a second copy of every customer's email;
that is what makes the endpoint safe to expose.

The jobs now return per-run counts so the caller's dashboard shows something
meaningful, and a null result distinguishes 'another instance had it' from
'ran and sent nothing'."
```

---

## Task 6: Container and platform configuration

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `render.yaml` (repo root), `frontend/vercel.json`
- Modify: `frontend/.env.example`, `backend/.env.example`

**Interfaces:**
- Consumes: `requirements.txt` from Task 4; `CRON_SECRET` from Task 5.
- Produces: a container that serves on `$PORT`; a Render blueprint; a Vercel SPA config.

- [ ] **Step 1: Write the Dockerfile**

Create `backend/Dockerfile`:

```dockerfile
# HaulCheck API.
#
# A container rather than a platform buildpack: the same image runs on Render,
# Railway, Fly, or any VPS. Being unable to move was the problem this migration
# exists to solve, so the deploy target stays interchangeable.
FROM python:3.12-slim

# reportlab and pillow render the PDF audit packs; both need the system image
# libraries at runtime, not just at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer is cached unless requirements.txt changes, so
# an application edit does not reinstall everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# A compromised dependency should not be able to write to the application.
RUN useradd --create-home --shell /usr/sbin/nologin haulcheck \
    && chown -R haulcheck:haulcheck /app
USER haulcheck

EXPOSE 8000

# The host assigns the port; binding a fixed one makes the health check fail
# with no useful error. 0.0.0.0 is required -- localhost is unreachable from
# outside the container.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 2: Write `.dockerignore`**

Create `backend/.dockerignore`:

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
.env.*
!.env.example
tests/
.pytest_cache/
requirements-dev.txt
*.md
.git/
```

`.env` is excluded deliberately: configuration comes from the host's environment, and baking a secrets file into an image distributes it to anyone who can pull that image.

- [ ] **Step 3: Build and run the image locally**

```bash
cd "backend"
docker build -t haulcheck-api .
docker run --rm -p 8000:8000 \
  -e MONGO_URL="mongodb://host.docker.internal:27017" \
  -e DB_NAME=haulcheck \
  -e JWT_SECRET=local-test-secret-not-for-production \
  -e ENVIRONMENT=development \
  haulcheck-api
```

Then in another shell:

```bash
curl -s http://localhost:8000/api/health
```

Expected: JSON naming the provider for each external service. `storage` should report `null` (no R2 credentials passed here) and `ai` should report `null`.

- [ ] **Step 4: Write the Render blueprint**

Create `render.yaml` at the **repository root**:

```yaml
# Render blueprint.
#
# Infrastructure as code so the deploy is repeatable and every variable is
# recorded in the repository, rather than living only in a dashboard one person
# can see.
#
# Values marked sync:false are set in the Render UI and never committed.
services:
  - type: web
    name: haulcheck-api
    runtime: docker
    plan: free
    region: frankfurt
    rootDir: "backend"
    dockerfilePath: ./Dockerfile
    healthCheckPath: /api/health
    envVars:
      - key: DB_NAME
        value: haulcheck
      - key: ENVIRONMENT
        value: production
      # Render terminates TLS at a proxy, so the socket peer is the proxy, not
      # the client. Without this every request looks like one IP and the per-IP
      # rate limits -- including the driver access-code sweep limit -- collapse
      # to a single shared bucket.
      - key: TRUST_PROXY_HEADERS
        value: "1"
      - key: STORAGE_PROVIDER
        value: s3
      - key: S3_REGION
        value: auto
      # AI ships off. Every call site degrades to its existing fallback.
      - key: AI_PROVIDER
        value: "null"
      - key: JWT_SECRET
        generateValue: true
      - key: CRON_SECRET
        generateValue: true
      - key: MONGO_URL
        sync: false
      - key: CORS_ORIGINS
        sync: false
      - key: S3_BUCKET
        sync: false
      - key: S3_ENDPOINT
        sync: false
      - key: S3_ACCESS_KEY
        sync: false
      - key: S3_SECRET_KEY
        sync: false
      - key: RESEND_API_KEY
        sync: false
      - key: SENDER_EMAIL
        sync: false
```

- [ ] **Step 5: Write the Vercel config**

Create `frontend/vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "create-react-app",
  "buildCommand": "yarn build",
  "outputDirectory": "build",
  "installCommand": "yarn install --frozen-lockfile",
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "DENY" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
      ]
    }
  ]
}
```

The rewrite matters: React Router owns routes like `/dashboard` and `/driver`, and without it a refresh on any route other than `/` returns a Vercel 404.

- [ ] **Step 6: Document the production shape of the frontend variable**

Replace `frontend/.env.example` with:

```
# Frontend environment. Copy to `.env` and fill in.
#   cp .env.example .env
#
# Base URL of the API host WITHOUT the /api suffix -- lib/api.js appends it.
# Local:      http://localhost:8000
# Production: https://haulcheck-api.onrender.com
#
# This is baked into the bundle at build time, not read at runtime, so changing
# it needs a redeploy of the frontend, not just an environment update.
REACT_APP_BACKEND_URL=http://localhost:8000

# Optional: enable the CRACO webpack health-check plugin (see craco.config.js).
# ENABLE_HEALTH_CHECK=true
```

- [ ] **Step 7: Note the proxy requirement in the backend example**

In `backend/.env.example`, replace the `TRUST_PROXY_HEADERS=` line and its comment block with:

```
# Trust the X-Forwarded-For header for per-IP rate limiting. Enable ONLY when
# the app sits behind a proxy/load balancer that overwrites the header --
# otherwise a client could forge it and bypass the driver-code sweep limit.
# Leave unset for a directly-exposed service; the real TCP peer is used instead.
#
# Render, Railway, Fly and Vercel all terminate TLS at a proxy, so set this to 1
# on any of them. Without it every request appears to come from the proxy's IP
# and all clients share one rate-limit bucket.
TRUST_PROXY_HEADERS=
```

- [ ] **Step 8: Verify the frontend builds with the production variable**

```bash
cd "frontend"
REACT_APP_BACKEND_URL=https://haulcheck-api.onrender.com yarn build
grep -rl "haulcheck-api.onrender.com" build/static/js/ | head -1
```

Expected: the build succeeds and at least one bundle contains the URL, confirming it is compiled in rather than read at runtime.

- [ ] **Step 9: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore render.yaml frontend/vercel.json frontend/.env.example backend/.env.example
git commit -m "Add container and platform configuration

A Dockerfile rather than a platform buildpack, so the same image runs on
Render, Railway, Fly or a VPS -- being unable to move hosts is the problem this
migration exists to solve, and a vendor buildpack would recreate it.

render.yaml records every variable in the repository instead of a dashboard.
It sets TRUST_PROXY_HEADERS=1, which Render needs: TLS terminates at a proxy,
so without it every request appears to come from one IP and the per-IP limits,
including the driver access-code sweep limit, share a single bucket.

vercel.json rewrites all paths to index.html; React Router owns /dashboard and
/driver, and a refresh on either 404s without it."
```

---

## Task 7: Confirm the AI features degrade visibly with AI switched off

The app ships with `AI_PROVIDER=null`. `NullAI.chat()` raises `AIUnavailable`, and every backend call site catches it — but a caught exception that returns nothing can still leave the interface spinning forever, which reads as a broken app rather than a disabled feature.

**Files:**
- Modify: whichever frontend components the audit in Step 1 identifies.
- Test: manual verification against a locally running stack.

**Interfaces:**
- Consumes: `providers.ai.NullAI` (exists), the five AI endpoints in `server.py`.
- Produces: no new modules. Any component changed keeps its existing `data-testid` values.

- [ ] **Step 1: Locate every AI call site on both sides**

```bash
cd "."
grep -rn "providers_ai\|get_provider()\.chat\|AIUnavailable" backend/server.py
grep -rn "/ai/\|ai_summary\|ai-summary" frontend/src --include=*.js
```

Record the five features and the component behind each: defect summaries, letter drafting, insurance import, fleet risk briefing, tacho printout analysis.

- [ ] **Step 2: Run the stack with AI off**

In `backend/.env` set:

```
AI_PROVIDER=null
```

Start the backend and frontend, and confirm the startup log contains:

```
AI provider: null
```

- [ ] **Step 3: Exercise each of the five features in the browser**

For each one, record what the user sees. The bar is: **a message that says the feature is unavailable, and no permanently spinning control.**

| Feature | Where | Acceptable | Not acceptable |
|---|---|---|---|
| Defect summary | Maintenance → a defect | "AI summary unavailable" | Spinner that never resolves |
| Letter drafting | Office → letters | Message, form still usable | Blank modal |
| Insurance import | Office → insurance | Message, manual entry still offered | Silent no-op on upload |
| Fleet risk briefing | Dashboard | Section hidden or captioned | Empty card with no explanation |
| Tacho printout analysis | Tacho | Message, manual entry still offered | Spinner that never resolves |

- [ ] **Step 4: Fix any that fail the bar**

For each failing component, ensure the request's `catch` clears loading state and sets a visible message. The pattern to follow, matching the existing components:

```javascript
} catch (err) {
  const unavailable = err?.response?.status === 503
    || /not configured|unavailable/i.test(err?.response?.data?.detail || "");
  setError(unavailable
    ? "AI features are not enabled for this account."
    : "Could not generate the summary. Please try again.");
} finally {
  setLoading(false);   // must run on the error path, or the control spins forever
}
```

Keep every existing `data-testid`; add one to any new message element, following the neighbouring naming.

- [ ] **Step 5: Re-verify all five**

Repeat Step 3. All five must now show a message and no stuck spinner.

- [ ] **Step 6: Confirm the null-provider tests still pass**

```bash
cd "backend"
pytest tests/test_provider_decoupling.py -n 0 -v
```

Expected: PASS, including `TestNullProvidersDegradeCleanly`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "Show AI features as unavailable rather than spinning

The app ships with AI_PROVIDER=null and every backend call site already catches
AIUnavailable -- but a caught error that clears no loading state leaves the
control spinning, which a user reads as a broken app rather than a feature that
is switched off.

Each of the five AI features now clears its loading state on the error path and
says so. Manual entry stays available wherever AI was only ever assisting."
```

If Step 3 found nothing to fix, skip this commit and note that in the task summary.

---

## Task 8: Write `DEPLOYMENT.md`

**Files:**
- Create: `DEPLOYMENT.md` at the repository root.

**Interfaces:**
- Consumes: everything above.
- Produces: the operator guide.

- [ ] **Step 1: Deploy it yourself first, and take notes**

Do not write this from the plan — write it from having done it. Work through in this order, recording every value and every place the real interface differs from what you expected:

1. **MongoDB Atlas** — free M0 cluster, Frankfurt. Database user. Network access `0.0.0.0/0` (Render's free tier has no static outbound IP, so an allow-list is not possible; the password is the control). Copy the `mongodb+srv://` string and insert the password.
2. **Cloudflare R2** — bucket `haulcheck`, jurisdiction EU. An API token scoped to *Object Read & Write* on that bucket only. Record the Account ID, Access Key ID, Secret. The endpoint is `https://<account-id>.r2.cloudflarestorage.com`.
3. **Resend** — API key, and a verified sender. Note that without a verified domain, sending is restricted to your own address.
4. **Render** — new Blueprint from the repo, which picks up `render.yaml`. Fill in every `sync: false` variable. Leave `CORS_ORIGINS` until step 6.
5. **Vercel** — new project, Root Directory `frontend`, `REACT_APP_BACKEND_URL` set to the Render URL with **no** trailing `/api`.
6. **Connect them** — set `CORS_ORIGINS` on Render to the exact Vercel production origin, then redeploy. The backend refuses to start when `ENVIRONMENT=production` and this is unset or `*`.
7. **cron-job.org** — daily 07:00 UTC, `POST https://<render-url>/api/tasks/run-reminders`, header `Authorization: Bearer <CRON_SECRET>` (copy the generated value from Render's environment tab).

- [ ] **Step 2: Run the live storage tests against the real bucket**

```bash
cd "backend"
export S3_BUCKET=haulcheck
export S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
export S3_ACCESS_KEY=... S3_SECRET_KEY=... S3_REGION=auto STORAGE_PROVIDER=s3
pytest tests/test_s3_storage.py -n 0 -v
```

Expected: the `TestRoundTripAgainstARealBucket` class now runs and passes. This is the first proof that SigV4 is right against a live endpoint — everything before it was checked against botocore, not Cloudflare.

- [ ] **Step 3: Run the full suite against the deployed backend**

```bash
export REACT_APP_BACKEND_URL=https://haulcheck-api.onrender.com
curl -s "$REACT_APP_BACKEND_URL/api/health"   # wake the instance first
pytest -n 0
```

The cold start exceeds most default timeouts, so the `curl` is required, not optional. Record any failures in `test_result.md` following its existing YAML structure, and preserve its DO-NOT-EDIT header.

- [ ] **Step 4: Write the guide**

Create `DEPLOYMENT.md`, matching the voice of the existing `CLIENT_SETUP.md` — short sentences, numbered steps, every value copy-and-pasteable, and a stated reason wherever a step looks arbitrary. Sections:

1. **What you are building** — the diagram from the spec, and the £0 cost table
2. **Accounts to create** — Atlas, Cloudflare, Render, Vercel, Resend, cron-job.org
3. **Put the code on GitHub**
4. **The database** — Atlas M0, why network access is `0.0.0.0/0`
5. **File storage** — R2 bucket and a bucket-scoped token
6. **Email** — Resend, and the sender-verification limit
7. **The backend** — Render blueprint, every variable, what each one does
8. **The frontend** — Vercel, Root Directory, `REACT_APP_BACKEND_URL`
9. **Connecting them** — `CORS_ORIGINS`, and why the backend refuses to start without it
10. **Daily reminders** — cron-job.org, the bearer header
11. **Smoke test** — the checklist from Step 5 below
12. **Known limits of the free tier** — 50-second cold start; Vercel Hobby is non-commercial per Vercel's terms, so a paying product needs Pro or a move to Cloudflare Pages; Atlas M0 is 512 MB; preview deployments cannot call the API because `CORS_ORIGINS` lists only the production origin
13. **When the domain arrives** — DNS on both platforms, update `CORS_ORIGINS`, then enable Google sign-in: create an OAuth Client ID, set the redirect URI to exactly `<frontend origin>/auth/google/callback`, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Explain that it is off until then because the session cookie is `SameSite=None` and Safari blocks that across two different domains.
14. **When you want AI on** — add `anthropic` to `requirements.txt`, set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`, redeploy. Note that the insurance-import and tacho-printout features read documents, so model quality shows there first.
15. **Going paid** — a cost table, when each free tier runs out, and Atlas backups

- [ ] **Step 5: Include this smoke-test checklist verbatim**

```markdown
## Smoke test

Work through this after every deploy. Each step exercises a different piece of
the stack, so where it stops tells you what is wrong.

- [ ] `https://<render-url>/api/health` returns JSON.
      Check `storage` says `s3` — `null` means the R2 variables did not take.
- [ ] The Vercel URL loads the login page.
- [ ] Register a new account. *(Backend, database write, password policy.)*
- [ ] Sign in. *(JWT issue and verify.)*
- [ ] Add a vehicle with an MOT date in the past.
      It must show as expired. *(Compliance calculation.)*
- [ ] Raise a defect and attach a photo. *(R2 upload — the piece most likely to fail.)*
- [ ] Reopen the defect and confirm the photo displays. *(R2 download.)*
- [ ] Generate a PDF audit pack and open it. *(reportlab in the container.)*
- [ ] Create a driver, then open `/driver` and sign in with the access code.
      *(The second, separate auth path.)*
- [ ] Trigger reminders manually:
      `curl -X POST -H "Authorization: Bearer $CRON_SECRET" https://<render-url>/api/tasks/run-reminders`
      Expect `{"ran": {...}}` and an email. *(Resend, and the cron path.)*
- [ ] Repeat the same call straight away. Expect `null` for the job that just ran
      — that is the lock preventing duplicate email.
```

- [ ] **Step 6: Have someone else follow it**

Give the guide to someone who has not seen this work and watch them follow it without helping. Every question they ask is a missing step. Fix those, then commit.

- [ ] **Step 7: Commit**

```bash
git add DEPLOYMENT.md test_result.md
git commit -m "Add the deployment guide

Written from actually performing the deployment rather than from the plan, so
the steps match what the dashboards really show.

Covers the free-tier limits honestly -- the 50-second cold start, Vercel
Hobby's non-commercial terms, and that preview deployments cannot reach the API
because CORS_ORIGINS lists only the production origin -- and carries the two
follow-on sections the client will need: turning Google sign-in on once a
domain exists, and turning AI on when they decide to."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 4.1 Finish `S3Storage` for R2 | 2, 3 |
| 4.2 One honest `requirements.txt` | 4 |
| 4.3 Frontend de-Emergent | 1 |
| 4.4 Delete platform files | 1 |
| 4.5 `Dockerfile` / `.dockerignore` | 6 |
| 4.6 `render.yaml` | 6 |
| 4.7 Cron endpoint | 5 |
| 4.8 AI-off degrades in the UI | 7 |
| 5. Configuration tables | 6, 8 |
| 5. Vercel preview CORS constraint | 6, 8 (§12) |
| 6. `DEPLOYMENT.md` | 8 |
| 7. Testing / acceptance gate | 8 (Steps 2-3) |
| 8. Risks | Mitigations in 2 (botocore differential), 4 (Step 6 import scan, Step 7 clean install), 8 (§12) |

**Added beyond the spec:** removal of the PostHog session-recording snippet (Task 1). Found during planning, not present in the spec: it records sessions of screens showing driver licence, CPC and tachograph data to an analytics project the client does not own.

**Type consistency:** `_sigv4.sign(...)` keyword signature is identical in Task 2's definition and Task 3's call. `sha256_hex` is public (no underscore) because Task 2's test uses it. `S3Storage._url`, `_send`, `_fail` are defined in Task 3 and used only there. `run_daily_reminders`/`run_weekly_reminders` return `dict` in Task 5's Step 3 and are consumed as `dict | None` in Step 4.
