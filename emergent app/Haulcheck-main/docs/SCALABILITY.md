# Scalability

What was fixed to let the platform hold more than one customer, and why each
thing mattered.

## Indexes (`backend/indexes.py`)

The application shipped with **no indexes at all** beyond MongoDB's automatic
`_id`. Every query was a full collection scan.

That is invisible with one operator's data and becomes the dominant cost as
tenants are added, because the scan grows with the *platform*, not the customer:
listing one org's vehicles had to read every vehicle belonging to every customer.

59 indexes are now declared and created at startup (idempotent, so it is safe on
every boot). Two design points:

**`org_id` leads every tenant index.** A compound index is only usable left to
right, so `(org_id, created_at)` serves "this org's records, newest first" while
`(created_at, org_id)` would not. `test_indexes.py` asserts that every collection
in `tenancy.ORG_COLLECTIONS` has an index led by `org_id`.

**One index is deliberately *not* org-scoped.** `drivers.access_code` is matched
across the whole platform at driver login, so it is indexed on its own. Without
it, each login attempt scanned every driver of every customer — slow, and a
denial-of-service lever.

Measured on the development database:

```
vehicles.find({org_id})   before: COLLSCAN, 21 docs examined -> 2 returned
                          after:  IXSCAN,    2 docs examined -> 2 returned
```

The ratio is the point, not the absolute numbers: before, documents examined
equals the whole collection; after, it equals the rows actually returned.

### A correctness fix, not just performance

`users.email` now has a **unique** index. Registration checked for an existing
address and then inserted — two concurrent requests could both pass the check
and create duplicate accounts for the same person, after which either record
could satisfy a login. The database is the only place that race can be closed.
`org_members` has a unique `(org_id, user_id)` for the same reason.

Startup reports any duplicate addresses it finds, because the unique index
cannot be built while they exist. Duplicates are reported rather than merged
automatically — deciding which record is authoritative is not a decision to make
silently.

## Scheduled jobs across replicas (`backend/scheduling.py`)

The reminder jobs ran on an in-process APScheduler started with the app. Correct
for one process; wrong the moment the service is scaled. With N replicas every
job fired N times — and these jobs **send email to customers**. Three replicas
meant three copies of every compliance reminder: invisible in a single-process
staging environment, immediately visible to the people paying for the product.

Jobs now claim a MongoDB-backed lock with an atomic `find_one_and_update`.
Whichever replica wins runs the job; the rest skip. No new infrastructure — the
database the app already depends on is the coordination point.

- Locks carry a **lease**, so a replica that dies mid-job does not block the
  schedule forever.
- Acquisition **fails closed**: if the lock cannot be evaluated the job is
  skipped. Missing one reminder run is recoverable; sending every customer
  duplicate emails is not.
- `test_scheduling.py` runs ten concurrent acquirers and asserts exactly one
  wins, because the failure only appears under concurrency.

## Blocking I/O on the event loop

Object storage used the synchronous `requests` library from inside `async def`
handlers. Every upload and download stalled the entire event loop for the
duration of the round trip, so one slow attachment fetch delayed every other
request the process was serving — the worst possible failure mode, because it
turns one slow dependency into a whole-service slowdown.

All 16 call sites now use async `httpx` through `providers/storage.py`. The
`asyncio.to_thread` wrappers that existed to hide the blocking are gone.

## Health endpoint

`GET /api/health` reports database round-trip latency and which provider each
external service resolved to. Returns **503** when MongoDB is unreachable, so an
orchestrator stops routing traffic to a replica that cannot serve. A missing
optional provider is reported but does not fail the check — the app still serves
every non-AI, non-upload request without one.

Unauthenticated by design (a probe has no credentials); it exposes nothing
beyond liveness and provider names.

## Still outstanding

- **Pagination.** List endpoints still use `.to_list(1000)`. The indexes make
  these fast, but an org with more than 1000 of anything silently truncates.
- **N+1 queries.** `gather_stats` and `detect_gaps` each issue ~10 sequential
  queries per dashboard load; they could run concurrently with
  `asyncio.gather`.
- **Structured logging** with request and org IDs.
