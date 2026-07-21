# Local development

How to run HaulCheck on a developer machine. Written for Windows (the machine
this was set up on) with notes for macOS/Linux.

The app was generated on the Emergent platform and originally only ran inside
that container: the backend assumed platform-managed services and the test
suite assumed the container's `/app` layout. Everything below exists to make it
run locally instead.

## What you need

| Tool | Version used | Notes |
|---|---|---|
| Python | 3.12 | **Not 3.14** — several pinned dependencies have no 3.14 wheels. `py -3.12` selects it on Windows. |
| Node.js | 24.x | Ships with npm; yarn is enabled through corepack. |
| MongoDB | 7.0 | Portable ZIP, no installer and no admin rights required. |

No Docker required.

## One-time setup

### 1. MongoDB (portable, no admin)

Download the Windows ZIP archive from
`https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.16.zip`, extract
it to `.tools/` at the repository root, and delete the `.pdb` debug symbols
(they are ~1.5 GB of the 1.7 GB archive and are not needed):

```bash
rm -f .tools/mongodb-win32-x86_64-windows-7.0.16/bin/*.pdb
```

`.tools/` and `.data/` are both gitignored. To remove MongoDB later, delete
those two directories — nothing is installed system-wide and no service is
registered.

On macOS/Linux use your package manager (`brew install mongodb-community@7.0`,
or the distribution package) and skip to step 2.

### 2. Backend

```bash
cd "emergent app/Haulcheck-main/backend"
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-local.txt   # Scripts -> bin on macOS/Linux
cp .env.example .env
```

Then generate a real signing secret and put it in `.env` as `JWT_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Why `requirements-local.txt` and not `requirements.txt`?** `requirements.txt`
is the Emergent *deployment* manifest — it pins the entire platform image
(pandas, boto3, litellm, google-genai, s5cmd…) and several of those pins have no
Windows wheels. `requirements-local.txt` is the minimum that actually runs the
app and the tests. Keep both in sync when adding a genuine runtime dependency.

### 3. Frontend

```bash
cd "emergent app/Haulcheck-main/frontend"
corepack enable && corepack prepare yarn@1.22.22 --activate
yarn install
cp .env.example .env
```

## Running

Three processes, three terminals. From the repository root:

```bash
# 1. MongoDB
.tools/mongodb-win32-x86_64-windows-7.0.16/bin/mongod.exe \
  --dbpath .data/mongo --port 27017 --bind_ip 127.0.0.1

# 2. API  ->  http://localhost:8000
cd "emergent app/Haulcheck-main/backend"
.venv/Scripts/python -m uvicorn server:app --reload --port 8000

# 3. Frontend  ->  http://localhost:3000
cd "emergent app/Haulcheck-main/frontend"
yarn start
```

Interactive API docs: <http://localhost:8000/docs>.

### Expected noise on startup

```
ERROR - Storage init failed: 400 Client Error ... /objstore/api/v1/storage/init
```

This is normal without a real `EMERGENT_LLM_KEY`. Object storage and every AI
feature are unavailable locally; everything else works. Both are wrapped in
`try`/`except`, so the app starts regardless.

## Tests

The suites in `backend/tests/` are **integration tests, not unit tests** — they
drive a live backend over HTTP. MongoDB *and* the API must already be running.

```bash
cd "emergent app/Haulcheck-main/backend"
.venv/Scripts/python -m pytest -n 0                        # serial (deterministic)
.venv/Scripts/python -m pytest                             # parallel, uses pytest.ini
.venv/Scripts/python -m pytest tests/backend_test.py::TestAuth -n 0   # one class
```

- Serial is `-n 0`. **Not** `-p no:xdist` — that errors, because `addopts` still
  passes `-n`/`--dist`.
- **Do not edit `addopts` in `pytest.ini`.** Its comment block explains the
  fixed two-worker `loadscope` pinning.
- Tests share a seed account, `manager@haulcheck.co.uk` / `Test1234!`, and
  register it automatically if missing. They also leave data behind by design —
  to reset, drop the database:
  ```bash
  .venv/Scripts/python -c "from pymongo import MongoClient; MongoClient('mongodb://127.0.0.1:27017').drop_database('haulcheck')"
  ```
- Tests touching AI or file upload fail locally without `EMERGENT_LLM_KEY`. That
  is environmental, not a regression — compare against the recorded baseline in
  `docs/TEST_BASELINE.md`.

### How tests find the API

`tests/conftest.py` resolves `REACT_APP_BACKEND_URL` before any test module is
imported, in this order:

1. the exported environment variable, if set (CI and the hosted preview keep
   working unchanged);
2. `frontend/.env`, located relative to `conftest.py`;
3. `http://localhost:8000`.

Eleven test files contain their own fallback that reads the hard-coded path
`/app/frontend/.env` — the Emergent container layout, which does not exist
locally. Every one of them checks the environment variable first, so `conftest.py`
makes those fallbacks unreachable without needing to edit the test files.

## Troubleshooting

**`KeyError: 'MONGO_URL'` (or `DB_NAME`, `JWT_SECRET`, `EMERGENT_LLM_KEY`) on
startup** — `server.py` reads these at module scope via `os.environ[...]`.
`backend/.env` is missing or incomplete; copy `.env.example` again.

**`ServerSelectionTimeoutError`** — MongoDB is not running, or `MONGO_URL`
points elsewhere. Check `.data/mongod.log`.

**Every test errors during collection** — the API is not running. Confirm with
`curl http://localhost:8000/api/auth/me` (401 is the healthy answer).

**CORS errors in the browser** — `CORS_ORIGINS` in `backend/.env` must contain
the frontend's exact origin, e.g. `http://localhost:3000`.

**`RequestsDependencyWarning: urllib3 ... doesn't match a supported version`** —
harmless; `requests` is only used for the Emergent object-store calls, which are
being moved to async `httpx` in Phase 4.
