# HaulCheck

A road-haulage compliance platform for UK (DVSA) and Ireland (RSA) transport
operators — converted from a single-user app into a multi-tenant SaaS.

> **Taking this over?** Start with **[HANDOVER.md](HANDOVER.md)** — what the app
> was, what changed, and the setup steps that need accounts in your own name.

It tracks vehicle MOT/CVRT, service, tax and PMI inspections; defects and
walkaround checks; driver licences, CPC and tachograph hours; operator licence
and insurance — then computes a compliance status and risk score and generates
PDF audit packs. Two audiences share one codebase: **fleet managers** on a
desktop dashboard, and **drivers** on a mobile-first defect/walkaround app.

---

## What this repository is

The first commit, `5bd74c9`, is HaulCheck exactly as exported from the
[Emergent](https://emergent.sh) platform — ~29 iterations of working features.
Every commit after it is the conversion to a SaaS platform.

The app worked. What it was not was multi-tenant: **"tenant" meant "one
individual user."** An invited colleague received their own empty account, so
two managers at the same haulage firm could not share a fleet. There was no
organisation, no platform administration, no rate limiting on the driver login,
and — measurably — **not one database index**.

The conversion is organised into phases, each committed separately, each gated
on the test suite showing no new failures.

---

## Status

### Done

| Phase | What shipped | Key files |
|---|---|---|
| **0** | Runnable local environment (the app previously only ran inside the Emergent container) + a triaged test baseline | [docs/DEVELOPMENT.md](emergent%20app/Haulcheck-main/docs/DEVELOPMENT.md), [docs/TEST_BASELINE.md](emergent%20app/Haulcheck-main/docs/TEST_BASELINE.md) |
| **1** | **Organisations as the unit of tenancy.** All 193 tenant queries rescoped from `user_id` to `org_id`; roles (`owner`/`manager`/`viewer`); idempotent backfill migration | [tenancy.py](emergent%20app/Haulcheck-main/backend/tenancy.py), [migrations/001_org_layer.py](emergent%20app/Haulcheck-main/backend/migrations/001_org_layer.py) |
| **2** | **Auth hardening.** Rate limiting with lockout, 12-char password policy, email verification, JWT revocation via `token_version`, CORS `*` refused outside development | [security.py](emergent%20app/Haulcheck-main/backend/security.py) |
| **3** | **Platform admin console.** Tenant/user management, metrics, append-only audit log, read-only impersonation | [admin_routes.py](emergent%20app/Haulcheck-main/backend/admin_routes.py), [audit.py](emergent%20app/Haulcheck-main/backend/audit.py), [pages/admin/](emergent%20app/Haulcheck-main/frontend/src/pages/admin/) |
| **4a** | **Provider interfaces** for storage, email and AI, so Emergent can be swapped out. Storage moved off blocking `requests` onto async `httpx` | [providers/](emergent%20app/Haulcheck-main/backend/providers/) |
| **4b** | All 6 AI call sites routed through the provider; temp-file handling moved out of the routes. No vendor SDK is imported outside `providers/` any more, and a guard enforces it | [providers/ai.py](emergent%20app/Haulcheck-main/backend/providers/ai.py), [test_provider_decoupling.py](emergent%20app/Haulcheck-main/backend/tests/test_provider_decoupling.py) |
| **4c** | **Standard Google OAuth** against the deployment's own client, replacing the Emergent-hosted exchange. State is single-use *and* bound to the initiating browser | [oauth.py](emergent%20app/Haulcheck-main/backend/oauth.py) |
| **5a** | **59 indexes**, single-flight scheduled jobs, `/api/health` readiness probe | [indexes.py](emergent%20app/Haulcheck-main/backend/indexes.py), [scheduling.py](emergent%20app/Haulcheck-main/backend/scheduling.py) |
| **5b** | **Pagination** on the collections that grow without bound, with `X-Total-Count` so truncation is never silent. Dashboard N+1 removed — ~20 sequential reads now run concurrently | [server.py](emergent%20app/Haulcheck-main/backend/server.py), [test_pagination.py](emergent%20app/Haulcheck-main/backend/tests/test_pagination.py) |

### To do

| Phase | What |
|---|---|
| **6** | Split `server.py` (~5,000 lines) into domain routers — move-only, no logic change, mounted on the same `/api` prefix so every URL is unchanged. **Deferred deliberately:** it is a maintainability tidy-up with no user-visible effect, and 64 models and 160 routes are interleaved rather than in blocks, so it is a large mechanical change best done with the full suite run between each step rather than alongside functional work. |
| — | Structured JSON logging with request and org IDs. |
| — | Billing. The org model already reserves `plan`, `plan_limits` and `subscription_status` so payments drop in without a second migration. Deliberately out of scope for now. |

### Test trajectory

Every phase was gated on **no new failures** against the recorded baseline.

| | Baseline | P1 | P2+3 | P4a | **P5** |
|---|---|---|---|---|---|
| Passed | 221 | 224 | 277 | 304 | **324** |
| Failed | 27 | 26 | 26 | 24 | **24** |

The 24 remaining failures are the documented baseline set: they need an
`EMERGENT_LLM_KEY` or `RESEND_API_KEY`, or they are tests that drifted from
deliberate product changes. Each one is triaged by cause in
[docs/TEST_BASELINE.md](emergent%20app/Haulcheck-main/docs/TEST_BASELINE.md) —
including four cases where **the app is right and the test is stale**, which are
called out so nobody "fixes" the app to satisfy them.

---

## Quickstart

Full instructions, including the portable no-admin MongoDB setup, are in
[docs/DEVELOPMENT.md](emergent%20app/Haulcheck-main/docs/DEVELOPMENT.md).

Requires **Python 3.12** (not 3.14 — several pinned dependencies have no 3.14
wheels), Node 24, MongoDB 7. No Docker.

```bash
# 1. MongoDB on 27017

# 2. API -> http://localhost:8000
cd "backend"
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-local.txt
cp .env.example .env          # then set a real JWT_SECRET
.venv/Scripts/python -m uvicorn server:app --reload --port 8000

# 3. Frontend -> http://localhost:3000
cd "frontend"
yarn install && cp .env.example .env && yarn start
```

Interactive API docs at `/docs`. Readiness probe at `/api/health` — it returns
**503** when MongoDB is unreachable, so an orchestrator stops routing to a dead
replica.

Use `requirements-local.txt`, not `requirements.txt` — the latter is Emergent's
deployment manifest and pins the whole platform image.

### Grant yourself platform admin

`platform_role` is **not grantable through any API**, by design. Self-registration
cannot reach it:

```bash
.venv/Scripts/python scripts/grant_admin.py you@example.com
```

---

## Layout

The application sits at the repository root.

```
├── backend/              FastAPI + MongoDB
│   ├── server.py         most routes and models (being split in Phase 6)
│   ├── tenancy.py        the only place an org filter is constructed
│   ├── security.py       rate limiting, password policy
│   ├── indexes.py        59 index declarations, created at startup
│   ├── scheduling.py     Mongo-backed leader lock for scheduled jobs
│   ├── audit.py          append-only audit log
│   ├── admin_routes.py   /api/admin
│   ├── providers/        storage, email, ai — vendor behind an interface
│   ├── tacho_engine.py   .ddd tachograph decoding + EU 561/2006 checks
│   ├── reports.py        report sections (data, not PDFs)
│   ├── pdf_export.py     reportlab rendering + attachment merging
│   └── tests/            integration tests — they drive a live HTTP backend
├── frontend/             React 19, CRACO, Tailwind, shadcn/ui
├── docs/                 development, security, scalability, test baseline
├── memory/PRD.md         feature history per iteration
└── design_guidelines.json
```

---

## How tenancy works

Every tenant collection is scoped by `org_id`, and `tenancy.tenant_filter()` is
the only place that filter is built. It **refuses to return a filter** when the
org context is missing, rather than quietly producing `{}` and matching every
customer's rows:

```python
def tenant_filter(actor: Actor, **extra: Any) -> dict:
    oid = org_id_of(actor)
    if not oid:
        raise HTTPException(
            status_code=500,
            detail="Organisation context missing; refusing to run an unscoped query")
```

### The guard that keeps it that way

[`tests/test_tenancy_guard.py`](emergent%20app/Haulcheck-main/backend/tests/test_tenancy_guard.py)
reads `server.py` as source and fails the build if a raw `user_id` filter
reappears on a tenant collection.

A source-level check rather than a behavioural one, because **a missing org
filter does not fail loudly.** The endpoint still returns 200 — just with another
customer's rows in it — and only a test that happened to have two populated
tenants would ever notice. A second test asserts that every collection
`server.py` touches is classified as either tenant data or an identity
collection, so a newly added collection cannot be silently unscoped.

Deliberate exceptions are marked at the call site, not in a list, so the
justification travels with the code:

```python
# tenancy: allow-user-scope -- runs before the org exists
op = await db.operator.find_one({"user_id": uid}, {"_id": 0})
```

This guard has caught real mistakes, including one where the right value was
passed under the wrong key (`{"user_id": org_id}`) — which scopes by person while
looking like it scopes by org — and one false positive of its own, where
`db.command("ping")` was being read as a collection named `command`.

---

## Notes for anyone picking this up

**Backend tests are integration tests.** They hit a live backend over HTTP;
MongoDB and the API must both be running. Run serially with `pytest -n 0` — *not*
`-p no:xdist`, which errors. Do not edit `addopts` in `pytest.ini`; its comment
block explains the worker pinning.

**Run the API with `TRUST_PROXY_HEADERS=1` for the test suite**, so rate-limit
tests can give themselves distinct client IPs and not lock out their neighbours.
In production set it **only** behind a proxy that overwrites `X-Forwarded-For`,
or a client can forge the header and bypass the driver-code limit.

**Rate limits are split per-identifier and per-address.** The per-IP buckets are
deliberately much looser than the per-account ones: an entire transport office
behind one NAT address shares an IP, and limits tight enough for a single account
would lock all of them out. That was found the hard way — a 191-error regression
run traced back to exactly this.

**Region matters.** `user.region` (`UK`/`IE`) switches terminology and units
throughout: MOT↔CVRT, Vehicle Tax↔Motor Tax, £↔€, DVSA↔RSA.

**Every interactive element needs a `data-testid`** — both the design spec and
the test convention depend on it.

---

## Security

Detail in [docs/SECURITY.md](emergent%20app/Haulcheck-main/docs/SECURITY.md) and
[docs/SCALABILITY.md](emergent%20app/Haulcheck-main/docs/SCALABILITY.md).

- Real `.env` files are gitignored and **must never be committed**; only
  `.env.example` templates are tracked.
- `platform_role` is grantable only via `scripts/grant_admin.py` against the
  database — never through an API.
- Impersonation is **read-only and audit-logged**, enforced centrally in
  `get_current_user` rather than per-route, so a new endpoint cannot forget it.
- `users.email` is now **uniquely indexed**. Registration previously checked for
  an existing address and then inserted — two concurrent requests could both pass
  and create duplicate accounts for one person. The database is the only place
  that race can actually be closed.
- Scheduled jobs claim a Mongo-backed lock. They send email to customers, so an
  unguarded in-process scheduler meant N replicas sent N copies of every
  compliance reminder — invisible in staging, immediately visible to the people
  paying for the product.
