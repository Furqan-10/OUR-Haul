#!/usr/bin/env bash
# Local dev/test launcher. TRUST_PROXY_HEADERS lets the auth-hardening tests
# give each test its own client IP via X-Forwarded-For (see docs/DEVELOPMENT.md).
export ENVIRONMENT=development
export TRUST_PROXY_HEADERS=1
exec ./.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --log-level warning "$@"
