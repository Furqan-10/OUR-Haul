# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**HaulCheck** — a road-haulage compliance web app for UK (DVSA) and Ireland (RSA) transport/fleet operators. Two audiences in one codebase: **fleet managers** (desktop dashboard) and **drivers** (mobile-first defect/walkaround reporting). It tracks vehicle MOT/service/tax, PMI inspections, defects, driver licence/CPC/tacho hours, operator licence, insurance, wheel-security and tacho downloads, computes compliance status + a risk score, and generates PDF audit packs.

Generated on the Emergent platform (`fastapi_react_mongo_shadcn` base image). The `.emergent/`, `test_result.md`, and `test_reports/` files are Emergent tooling conventions — see [Testing](#testing).

## Repository layout

The actual application lives **two levels down** from this file:

```
emergent app/Haulcheck-main/
├── backend/    FastAPI + MongoDB (Python)
├── frontend/   React 19 (CRA + CRACO)
├── memory/PRD.md          product/iteration history (read for feature context)
├── design_guidelines.json design system source of truth
├── test_result.md         agent testing protocol + state (preserve the header block)
└── test_reports/          per-iteration pytest JSON output
```

Run all commands from `backend/` or `frontend/` inside `emergent app/Haulcheck-main/`, not from this root.

## Commands

**Frontend** (from `frontend/`, package manager is **yarn 1.22**):
- `yarn start` — dev server on :3000 (CRACO, not raw react-scripts)
- `yarn build` — production build
- `yarn test` — CRA/Jest component tests

**Backend** (from `backend/`, needs a `.env` — see [Environment](#environment)):
- `uvicorn server:app --reload` — run the API
- `pytest` — run the backend suite

### Backend tests are integration tests, not unit tests
`backend/tests/*` hit a **live running backend** over HTTP at `REACT_APP_BACKEND_URL` (falls back to reading `/app/frontend/.env`). They require the API + MongoDB to be up. They use a seed manager account `manager@haulcheck.co.uk` / `Test1234!` (auto-registered if missing).
- `pytest.ini` pins `addopts = -n 2 --dist loadscope` (pytest-xdist). **Do not modify `addopts`** — the comment block explains why (shared preview backend, per-class worker pinning).
- Run **serially** with `pytest -n 0` (NOT `-p no:xdist`, which errors).
- Single test: `pytest tests/backend_test.py::TestAuth::test_login_seed_account -n 0`
- Tests are grouped by feature iteration (`test_iter13_features.py` … `test_iter29_*.py`).

## Backend architecture

Almost everything is in **`backend/server.py`** (~4300 lines): all Pydantic models, auth, and every route. Routes are registered on `api_router = APIRouter(prefix="/api")`, so **all endpoints are under `/api`**. Three pure-logic modules are extracted out and imported by `server.py`:
- **`tacho_engine.py`** — deterministic `.ddd` digital-tachograph binary decoding + EU 561/2006 drivers'-hours infringement checks (`parse_ddd`, `parse_ddd_last_timestamp`, `detect_ddd_infringements`). No DB/FastAPI coupling.
- **`reports.py`** — builds report *sections* (title, meta, tables) per report kind, region-aware. Returns data structures, not PDFs.
- **`pdf_export.py`** — renders those sections to PDF with reportlab and merges attachment packs with pypdf (`build_report_pdf`, `merge_pack`, `concat_pdfs`, etc.).

### Auth — three separate schemes
`_authenticate()` deliberately **prefers a Bearer JWT over the session cookie** (a stale Google-session cookie on a shared browser must not override a fresh email/invite login).
- **Manager JWT** — email/password login issues an HS256 JWT (`JWT_SECRET`); sent as `Authorization: Bearer`. Guard: `get_current_user`.
- **Google OAuth** — Emergent-hosted OAuth returns a `session_id` in the URL hash; `AuthCallback` exchanges it for a `session_token` cookie stored in `db.user_sessions`. The frontend `AuthContext` skips its `/auth/me` check while a `session_id=` hash is present.
- **Driver JWT** — a separate token with `role: "driver"`; guard: `get_current_driver`. Drivers log in with a short access code (also encoded in an onboarding QR at `/driver?code=…`).

### Multi-tenancy
Every collection is scoped by `user_id`; queries always filter on it — preserve this on any new endpoint. Invited team members are provisioned via `_seed_template()`.

### Region (`user.region`)
`"UK"` vs `"IE"` switches terminology and units throughout: MOT↔CVRT, Vehicle Tax↔Motor Tax, £↔€, "DVSA (UK)"↔"RSA (Ireland)". `reports._terms(region)` centralizes the strings; server.py has inline `user.region == "IE"` checks too.

### Compliance model
`compliance_status(days, soon_days=30)` → `expired` (<0) / `due_soon` (≤soon_days) / `valid`, computed from expiry-date fields via `days_until()`. Tacho uses `TACHO_SOON_DAYS = 7`. Server also computes a 0–100 risk score with Low/Moderate/High bands.

### External services (all keyed off env)
- **Object storage** — Emergent objstore REST API (`init_storage`/`put_object`/`get_object`), authenticated with `EMERGENT_LLM_KEY`. Initialized on FastAPI startup.
- **AI** — `emergentintegrations.llm.chat.LlmChat` with `("openai", "gpt-5.4")` via `EMERGENT_LLM_KEY`, for defect summaries, letter drafting, insurance import, and fleet risk briefing.
- **Email** — Resend (`RESEND_API_KEY`, `SENDER_EMAIL`) for defect alerts, reminders, and audit-pack delivery.
- **Scheduler** — APScheduler `AsyncIOScheduler` started on app startup: daily reminders 07:00 UTC, weekly Mondays 07:00 UTC.

## Frontend architecture

React 19, **CRA driven by CRACO** (`craco.config.js`, not ejected), Tailwind + shadcn/ui (Radix primitives in `src/components/ui/`), `react-router-dom` v7. Import alias **`@` → `src`**.

- **Two apps, one bundle.** `App.js` wraps manager routes in `<Protected><Layout>…` (redirect to `/login` when unauthenticated); the driver app is a single public mobile route `/driver` (`pages/driver/DriverApp.js`). Many legacy paths `<Navigate>`-redirect into consolidated pages (e.g. `/defects` → `/maintenance`).
- **API clients.** `lib/api.js` (manager) is an axios instance with `baseURL = REACT_APP_BACKEND_URL + "/api"`, `withCredentials: true`, and a request interceptor that attaches `Bearer` from `localStorage.token`. `lib/driverApi.js` is the driver equivalent. Auth state lives in `context/AuthContext.js`.
- **CRACO extras.** Optional webpack health-check plugin (gated by `ENABLE_HEALTH_CHECK`), dev-server v5 compat shim, and Emergent `@emergentbase/visual-edits` babel wrapper injected in dev only.

### Design system (`design_guidelines.json`)
Swiss / high-contrast "control-room" light theme. **Chivo** for headings, **IBM Plex Sans** for body/data (never Inter/Roboto for headings). Traffic-light compliance colors (green/amber/red). Icons: lucide-react. **Every interactive/informational element needs a `data-testid`** — the backend integration test convention and the design spec both depend on it.

## Environment

`.env` files are gitignored and **not present in the repo** — you must supply them.

- `backend/.env`: `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `EMERGENT_LLM_KEY`, `RESEND_API_KEY`, `SENDER_EMAIL`, `CORS_ORIGINS` (comma-separated, default `*`).
- `frontend/.env`: `REACT_APP_BACKEND_URL` (base URL of the API host, no trailing `/api`).

## Testing protocol (Emergent)

`test_result.md` is the shared state/communication file between the main and testing agents; its header block is marked **DO NOT EDIT** — preserve it. Record task status in the YAML structure it defines and bump `stuck_count` for recurring failures. Development proceeds in numbered iterations; each run's results land in `test_reports/iteration_N.json`, and `memory/PRD.md` narrates the feature history per iteration.
