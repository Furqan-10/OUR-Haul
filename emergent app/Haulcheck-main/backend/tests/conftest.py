"""Shared test bootstrap.

The suites here are integration tests: they drive a *live* backend over HTTP
rather than importing `server`. Each one resolves the API base URL at module
import time from `REACT_APP_BACKEND_URL`, and eleven of them fall back to
reading the hard-coded Linux path `/app/frontend/.env` -- the layout of the
Emergent container. That path does not exist on a developer machine, so the
fallback raised and collection failed before a single test ran.

pytest imports conftest before any test module, and every one of those
fallbacks checks the environment variable *first*. So populating the variable
here repairs all of them at once, without touching the test files themselves.

Resolution order:
  1. REACT_APP_BACKEND_URL already exported  -> respected, never overridden,
     so CI and the hosted preview keep working unchanged.
  2. frontend/.env, located relative to this file rather than assumed at /app.
  3. http://localhost:8000, the default in frontend/.env.example.
"""
import os
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:8000"
# tests/ -> backend/ -> Haulcheck-main/ -> frontend/.env
FRONTEND_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"


def _from_frontend_env() -> str | None:
    try:
        for line in FRONTEND_ENV.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
                if value:
                    return value
    except OSError:
        pass
    return None


def _resolve_base_url() -> str:
    return (
        (os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
        or _from_frontend_env()
        or DEFAULT_BASE_URL
    )


# Set before test modules are imported -- this is what makes the /app fallbacks
# unreachable. Exported so tests spawned by xdist workers inherit it too.
os.environ["REACT_APP_BACKEND_URL"] = _resolve_base_url()
