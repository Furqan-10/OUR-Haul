# Security model

What protects the platform, and where the boundaries are. Written as the
controls were added during the SaaS conversion; read alongside
`backend/tenancy.py` (isolation) and `backend/security.py` (auth hardening).

## Tenant isolation

The unit of tenancy is the **organisation**. Every customer-data document
carries `org_id`, and every query is scoped through
`tenancy.tenant_filter()` — the single place an org filter is constructed. Two
guards keep this from eroding:

- `tests/test_tenancy_guard.py` fails the build if any route reintroduces a raw
  `user_id` filter on a tenant collection.
- `tests/test_org_tenancy.py` proves, over HTTP, that colleagues in one org
  share records while other orgs see nothing — including that a foreign record
  id returns **404, not 403**, so existence cannot be probed.

`tenant_filter()` raises rather than returning an unscoped filter when org
context is missing: a request with no tenant fails closed.

## Authentication

### Passwords
- Minimum 12 characters, plus a blocklist of common/guessable values and a
  check against the user's own name and email (`security.password_problem`).
- Follows NIST SP 800-63B in spirit: length and a blocklist rather than
  composition rules that merely produce `Password1!`.
- Applied identically at registration, invitation acceptance and password
  reset. Registration previously enforced *no* rule at all.

### Rate limiting and lockout (`backend/security.py`)

Each endpoint has **two** limits with different jobs, and the split matters:

| | Limit | Purpose |
|---|---|---|
| per identifier (email / access code) | tight — 10 logins, 8 codes | protects the account an attacker is targeting |
| per address (IP) | loose — 100 logins, 30 codes | coarse bulk-abuse control |

- `POST /auth/login` — per email and per IP.
- `POST /driver/login` — per code and per IP. This is what actually closes the
  driver-code hole: the code is matched across the whole platform, so only an
  attempt limit makes guessing infeasible. Note that **sweeping** distinct codes
  is stopped only by the address limit, because each guess is a different code
  and the per-code limit never fires. 30 attempts per 15 minutes still turns the
  legacy 31^6 keyspace into millions of years.
- State lives in MongoDB with a TTL index, not in process memory, so it is
  shared across replicas and survives a deploy. Identifiers are stored hashed.
- The check runs **before** the credential comparison, so a locked-out caller
  never reaches it.

> **Why the address limit is deliberately loose.** The first implementation
> limited per IP as tightly as per account. Whole organisations sit behind one
> public IP, so unrelated colleagues accumulated into a single bucket — a few
> mistyped passwords across a transport office would have locked out everyone in
> it. The regression that exposed this is kept as
> `TestSharedAddressIsNotPunished`: several accounts failing from one address,
> all of whom must still be able to sign in.

### Client IP (`security.client_ip`)
Per-IP limiting is only as trustworthy as the address it sees. By default the
real TCP peer is used, which cannot be forged. `X-Forwarded-For` is honoured
**only** when `TRUST_PROXY_HEADERS=1` — set that solely when the app runs behind
a proxy that overwrites the header, or an attacker could rotate it to evade the
per-IP limit.

### Token revocation
Session JWTs are stateless, so revoking one before it expires means versioning:

- Managers carry `tv` (the account's `token_version`), checked in
  `_authenticate`. It is bumped on password reset and on member deactivation,
  which immediately retires every token issued earlier. Previously a
  deactivated member's bearer token kept working for up to seven days.
- Drivers carry `cv` (`code_version`), checked in `get_current_driver`. Rotating
  or revoking an access code bumps it, so a lost handset's 30-day token dies at
  once. The long lifetime is deliberate — drivers use it at the roadside — and
  is safe because it is now revocable.

### Roles
`owner` > `manager` > `viewer`. Read-only enforcement for viewers, and for
impersonated sessions, lives in `get_current_user` — not per route — so an
endpoint added later cannot forget it.

## File access

Attachments are served only with the token in the `Authorization` header or the
session cookie. The former `?auth=<token>` query parameter was removed: a
credential in a URL is written to proxy and access logs, kept in browser
history, and forwarded in the `Referer` header. The frontend fetches protected
files as blobs (`frontend/src/lib/authedFile.js`).

## CORS

`allow_origins=["*"]` with `allow_credentials=True` is invalid and unsafe —
browsers reject the wildcard on credentialed requests, and the framework then
echoes the caller's origin, allowing any site with cookies attached. An explicit
origin list is now required; outside development the app refuses to start
without one.

## Email verification

Self-registered accounts start unverified and are prompted to confirm their
address. This is currently a **prompt, not a gate** — access is not restricted —
because email delivery is environment-dependent and gating would lock out every
account created before the feature. Accounts predating it are grandfathered as
verified. The `email_verified` flag and `/auth/verify-email` /
`/auth/resend-verification` endpoints are in place for gating to be switched on
once delivery is confirmed in production.

## Platform administration

The console at `/api/admin` (UI: `/admin`) reaches across every organisation, so
its own access control matters more than any single tenant's.

**The role cannot be granted through the API.** `platform_role` is set only by
`backend/scripts/grant_admin.py`, run against the database by someone with
server access. Registration and OAuth both hard-code the ordinary role, and a
test asserts that passing `platform_role` in a registration body is ignored.

**Unauthorised callers get 404, not 403.** The admin surface does not confirm it
exists to someone who cannot use it.

**Every action is audited** to an append-only `audit_log` collection — including
*reads* of a specific tenant, because looking at a customer's compliance data is
itself worth being able to account for. Nothing in the codebase updates or
deletes from that collection and no route exposes a mutation; a log an
administrator can quietly edit is not evidence. Entries are denormalised (actor
email, org name copied at write time) so they still read correctly after the
accounts they refer to are renamed or deleted.

**Impersonation is read-only and short-lived.** A support token lasts 60 minutes,
carries `impersonated_by`, and cannot write — enforced in
`server.get_current_user`, not per route. Being able to *act* as a customer
would put changes in their compliance record that they never made, which would
undermine the audit trail the product exists to produce. An impersonated session
also cannot reach the admin API, so there is no escalation loop. The UI shows a
persistent, undismissable banner naming the account being viewed.

**Deleting a tenant requires typing its name back.** It destroys statutory
evidence — inspection sheets, defect history, tacho records an operator may be
legally required to retain — so a mistyped id is not enough. Member *users* are
detached rather than deleted: a person may belong to another organisation, and
their identity is not one tenant's property.

## Known follow-ups

- **Google OAuth** still exchanges its session through
  `demobackend.emergentagent.com`. Replacing it with a standard Google OAuth
  client is Phase 4 (provider decoupling) and needs a Google Cloud client
  ID/secret.
- **UTC vs local dates** — compliance date maths runs in UTC while some inputs
  are local; can shift a due date by a day near midnight. Tracked from the
  Phase 0 baseline.
