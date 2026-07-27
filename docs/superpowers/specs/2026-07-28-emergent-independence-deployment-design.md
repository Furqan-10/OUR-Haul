# HaulCheck — Emergent independence and self-hosted deployment

**Date:** 2026-07-28
**Branch:** `saas-conversion`
**Status:** Approved, ready for implementation planning

---

## 1. Goal

Make HaulCheck run entirely on infrastructure the client controls, and deploy it
to a free-tier stack suitable for testing and customer demos.

The client owns the application and will acquire haulage-operator customers
himself, so this is the **multi-tenant SaaS**, not a single-customer instance.
The org/tenancy layer that makes that possible already exists; this work is about
hosting, not features.

### Success criteria

1. `git clone` → deploy on Render and Vercel with no Emergent account, key, or
   package involved.
2. File uploads (defect photos, signed walkaround sheets, certificates) work
   against Cloudflare R2.
3. No third-party script loads in the browser that the client did not choose.
4. Daily and weekly reminder emails fire reliably on a free tier that sleeps.
5. Running cost £0/month for testing, with a documented upgrade path.
6. The existing integration suite passes against the deployed backend.

### Non-goals

- Turning AI features on. They ship disabled (`AI_PROVIDER=null`) and every call
  site already has a try/except and a fallback. Enabling them later is one
  environment variable plus a key.
- Restructuring the repository. `emergent app/Haulcheck-main/` stays; both Render
  and Vercel support a root-directory setting.
- Custom domain setup as blocking work. The client will buy a domain later; the
  guide covers it as a clearly-marked follow-on section.
- Migrating existing data out of Emergent's object store. No production data
  exists there yet. If that changes, a copy script becomes a separate task.

---

## 2. Starting position

Earlier phases did most of the decoupling. `backend/providers/` defines an
interface per external service, selected by environment variable, with the
Emergent implementation as the current default and a null implementation so the
app boots with no keys at all.

| Service | Emergent impl | Alternative | State |
|---|---|---|---|
| AI | `EmergentLLM` | `AnthropicAI` | Working — `AI_PROVIDER=anthropic` |
| Storage | `EmergentStorage` | `S3Storage` | **Stub.** `_sign()` raises `NotImplementedError` |
| Email | Resend | — | Already portable |
| Google sign-in | Emergent demo backend | native `backend/oauth.py` | Done; Emergent path off by default |

Multi-tenancy, 59 database indexes, and a MongoDB-backed scheduler lock
(`backend/scheduling.py`) are already in place.

### What still blocks a deploy elsewhere

1. **`S3Storage` is unfinished** — the only hard code blocker. Every upload fails
   the moment the app leaves Emergent.
2. **`backend/requirements.txt` cannot install off-platform.** It is the Emergent
   *image* manifest: `emergentintegrations==0.2.0` is not on PyPI, and line 58
   pulls litellm from `customer-assets.emergentagent.com`. Any Render build dies
   there.
3. **`dnspython` is missing from `requirements-local.txt`.** MongoDB Atlas issues
   `mongodb+srv://` URIs, which silently require it. First deploy would fail with
   an unhelpful connection error.
4. **`frontend/public/index.html:38` loads a live script from `assets.emergent.sh`**
   on every page view — third-party JavaScript inside a compliance product, and a
   GDPR exposure.
5. **`frontend/package.json:84`** installs `@emergentbase/visual-edits` from
   `assets.emergent.sh`. If that host disappears, `yarn install` breaks.
6. Emergent URLs in the canonical link, `robots.txt` and `sitemap.xml`.
7. `.emergent/` (platform image reference, cron shell scripts) and `.gitconfig`,
   which sets the committer to `github@emergent.sh`.

---

## 3. Target architecture

```
Browser
   │
   ├──► Vercel  ·  static CRA build  ·  haulcheck.vercel.app
   │       └─ REACT_APP_BACKEND_URL ──┐
   │                                  ▼
   └──────────────────────► Render Web Service (Docker, free tier)
                              haulcheck-api.onrender.com
                                  ├──► MongoDB Atlas M0      (free, Frankfurt)
                                  ├──► Cloudflare R2         (free, 10 GB)
                                  └──► Resend                (free, 3k/month)

   cron-job.org ──► POST /api/tasks/run-reminders  ·  daily 07:00 UTC
```

**AI:** `AI_PROVIDER=null`.
**Google sign-in:** `GOOGLE_CLIENT_ID` blank, so the button is hidden. Enabled
when the domain arrives.

### Why this shape

**Split frontend and backend (chosen over a single container).** The frontend is
a static bundle on a CDN, so it loads instantly and stays up while the free-tier
backend sleeps — prospects see the app shell rather than a blank 50-second wait.
The trade-off accepted: Google sign-in relies on a `SameSite=None` cookie
(`server.py:1804`) which Safari's tracking prevention blocks cross-site, so
Google stays off until both halves sit under one domain. Email/password login
uses a Bearer JWT from `localStorage` and is unaffected.

**Docker on Render rather than a native Python service.** The image runs
unchanged on Railway, Fly, a VPS, or Hugging Face Spaces. Avoiding lock-in is the
point of the exercise; tying the deploy to one vendor's buildpack would repeat
the original mistake.

**Render over Railway.** Railway removed its free tier in August 2023 — a
one-time trial credit, then $5/month. Render's free web service is genuinely free
and adequate for testing.

---

## 4. Work items

### 4.1 Finish `S3Storage` for Cloudflare R2

The only real feature work.

- Implement AWS Signature V4 over `httpx`, **not boto3**. boto3 is synchronous;
  calling it from `async def` handlers would reintroduce the exact event-loop
  blocking that `providers/storage.py` was rewritten to eliminate (see its
  module docstring).
- Implement `put`, `get`, `delete`, `healthy`.
- Path-style URLs: `https://<account>.r2.cloudflarestorage.com/<bucket>/<key>`.
  R2 uses region `auto`.
- Delete `S3Storage._unimplemented` and the `_sign` stub.

**Testing:** signing is verified offline against AWS's published SigV4 test
vectors (canonical request → string to sign → signature), so correctness does not
depend on a live bucket. A round-trip integration test runs only when `S3_*` env
vars are present, and is skipped otherwise.

### 4.2 One honest `requirements.txt`

Rebuild from `requirements-local.txt`, which reflects what the code actually
imports, plus `resend` and `dnspython`. Move `pytest`, `black`, `flake8`, `mypy`
and `isort` to `requirements-dev.txt`.

Removed: `emergentintegrations`, the URL-pinned `litellm`, `pandas`, `boto3`,
`google-*`, `s5cmd`, `stripe`, `jq`, `openai`, `tiktoken`, `tokenizers`,
`huggingface_hub`, and the rest of the platform image.

**Risk:** something imports a dropped package. Mitigated by an import scan across
`backend/` and a clean-container boot before this is considered done.

`providers/ai.py` imports `emergentintegrations` lazily *inside* `chat()`, so
with `AI_PROVIDER=null` it is never reached.

### 4.3 Frontend de-Emergent

- Remove the `@emergentbase/visual-edits` dependency (`package.json:84`) and the
  `withVisualEdits` block (`craco.config.js:131-145`).
- Delete the `assets.emergent.sh` script tag (`index.html:38`).
- Replace the canonical URL (`index.html:19`), the `robots.txt` sitemap line and
  the `sitemap.xml` locations. They point at `transport-verify-3.emergent.host`
  and currently tell search engines the app lives on Emergent's domain.
- Add `engines.node` to pin Vercel's Node version — none is declared today, so
  Vercel picks its current default and that will drift.
- Add `vercel.json` with an SPA rewrite so React Router deep links resolve.

### 4.4 Delete platform files

`.emergent/` and `.gitconfig`. `test_result.md` and `test_reports/` stay — CLAUDE.md
requires preserving them.

### 4.5 Backend `Dockerfile` and `.dockerignore`

`python:3.12-slim`, non-root user, binds `$PORT` (Render injects it and health
checks fail if the app binds a fixed port).

### 4.6 `render.yaml` blueprint

Infrastructure as code, so a redeploy is repeatable and every environment
variable is recorded in the repository rather than existing only in a dashboard
that one person can see.

### 4.7 Cron endpoint for reminders

Render's free tier sleeps after 15 minutes idle, so the in-process APScheduler
never reaches 07:00.

- `POST /api/tasks/run-reminders`, guarded by a `CRON_SECRET` bearer token.
- Runs the daily job always; runs the weekly job as well when the UTC weekday is
  Monday. One cron entry for the operator to configure rather than two.
- Wraps both in the existing `scheduling.run_once(...)` Mongo lock, so it cannot
  double-send if APScheduler also fires on a paid tier later.
- Accepts an optional `?job=daily|weekly` override for manual testing.
- Returns per-job counts so cron-job.org's dashboard shows a meaningful result.

**Testing:** a request with a missing or wrong secret is rejected; a valid request
is idempotent within the lock TTL.

### 4.8 Verify AI-off degrades in the UI

The backend raises `AIUnavailable`, which every call site catches. Confirm all
five features — defect summaries, letter drafting, insurance import, fleet risk
briefing, tacho printout analysis — surface a clear message in the interface
rather than an endless spinner or a raw error.

---

## 5. Configuration

### Render (backend)

| Variable | Value | Note |
|---|---|---|
| `MONGO_URL` | Atlas `mongodb+srv://…` | The `+srv` form needs `dnspython` installed |
| `DB_NAME` | `haulcheck` | |
| `JWT_SECRET` | generated | Rotating it invalidates every token |
| `ENVIRONMENT` | `production` | Forces explicit CORS |
| `CORS_ORIGINS` | Vercel production origin | Also governs OAuth redirects |
| `TRUST_PROXY_HEADERS` | `1` | **Required.** Render terminates TLS at a proxy; without this every request appears to come from one IP and per-IP rate limits misfire |
| `STORAGE_PROVIDER` | `s3` | |
| `S3_BUCKET` / `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | R2 values | |
| `S3_REGION` | `auto` | R2 requires `auto` |
| `AI_PROVIDER` | `null` | |
| `EMAIL_PROVIDER` / `RESEND_API_KEY` / `SENDER_EMAIL` | Resend values | |
| `CRON_SECRET` | generated | New |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | unset | Hides the button until the domain exists |

### Vercel (frontend)

| Variable | Value |
|---|---|
| `REACT_APP_BACKEND_URL` | Render URL, **no trailing `/api`** |

Root directory on both platforms: `emergent app/Haulcheck-main/backend` and
`emergent app/Haulcheck-main/frontend` respectively.

### Known constraint: Vercel preview deployments

Every preview deployment gets a unique URL. `CORS_ORIGINS` is an explicit
allow-list that also validates OAuth redirect URIs (`server.py:5095`), so
previews cannot reach the API. Only the production origin is allowed. This is the
safe default — widening it to a wildcard pattern would let any `*.vercel.app`
subdomain call a credentialed API — and it is documented rather than worked
around.

---

## 6. Deliverable

`DEPLOYMENT.md`, in the same plain voice as the existing `CLIENT_SETUP.md`, aimed
at an operator who is not a developer:

1. Accounts to create — Atlas, Cloudflare, Render, Vercel, Resend, cron-job.org
2. Getting the code onto GitHub
3. Database — Atlas M0, network access, connection string
4. Storage — R2 bucket, API token, CORS on the bucket
5. Backend on Render
6. Frontend on Vercel
7. Connecting the two — `CORS_ORIGINS` and `REACT_APP_BACKEND_URL`
8. Daily reminders — cron-job.org
9. Smoke-test checklist
10. When the domain arrives — DNS, `CORS_ORIGINS`, enabling Google sign-in
11. When to turn AI on
12. Going paid — cost table, backups, when each free tier runs out

---

## 7. Testing

The existing suite is integration-style, hitting a live backend over HTTP, so
after deployment it doubles as the acceptance gate: point `REACT_APP_BACKEND_URL`
at the Render URL and run `pytest -n 0`.

Note that the free tier's cold start exceeds most default HTTP timeouts. The
first request must warm the instance before the suite runs.

New offline tests:

- SigV4 signing against AWS test vectors
- `S3Storage` round trip (skipped without `S3_*` env vars)
- Cron endpoint rejects a missing or wrong secret
- No file under `backend/` or `frontend/src/` references an Emergent host

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| SigV4 implemented incorrectly | AWS published test vectors, offline; then a scratch bucket before any real evidence is stored |
| Pruning `requirements.txt` breaks an import | Import scan across `backend/`, then a clean-container boot |
| Atlas M0 512 MB fills | Documented upgrade trigger; evidence files live in R2, not the database |
| Free-tier cold start looks like an outage to a prospect | Documented; the Vercel frontend loads instantly and the guide covers upgrading to $7/month before any live demo |
| Google sign-in unavailable until the domain exists | Accepted deliberately. Button auto-hides; email/password is the primary path |
| `CRON_SECRET` leaks | Bearer token over HTTPS, rotatable; the endpoint only triggers jobs that are already idempotent under the Mongo lock |

---

## 9. Decisions and their reasons

| Decision | Reason |
|---|---|
| Vercel + Render split | Client's stated preference; CDN frontend stays up while the backend sleeps |
| Render, not Railway | Railway has no free tier since August 2023 |
| Cloudflare R2 | Zero egress fees, and defect photos are re-served on every view |
| AI off at launch | Client will decide later; every call site already degrades |
| Google sign-in off at launch | Cross-site cookie blocked by Safari without a shared domain |
| External cron rather than keeping the instance awake | Keeping it awake burns the 750 free hours in ~31 days |
| Repository layout unchanged | Both platforms support a root directory; a flatten would rewrite every documented path for cosmetic gain |
| Docker rather than a native buildpack | Portability is the goal; a vendor buildpack would repeat the original lock-in |
