"""Static guard: tenant data must never be queried by raw user_id.

This is the regression test that stops org scoping from rotting back into
per-user scoping. Unlike its neighbours it imports nothing and needs no running
backend — it reads the source and fails the build on a bad pattern.

Why a source-level check rather than a behavioural one: a missing org filter
does not fail loudly. The endpoint still returns 200, just with another
customer's rows in it, and only a test that happens to have two populated
tenants would notice. Catching the pattern itself is far more reliable than
hoping an integration test trips over the consequence.

Scoping a query on `user_id` narrows to one *person*, but tenancy is per
*organisation* — colleagues sharing a fleet must see the same records. So for
any collection holding customer data, `user_id` is the wrong key and `org_id`
is the right one. Route code must go through `tenancy.tenant_filter()`.
"""
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"

# Collections holding tenant data, imported from the same tuple the runtime
# uses so the two can never drift apart.
import sys  # noqa: E402
sys.path.insert(0, str(BACKEND))
from tenancy import ORG_COLLECTIONS  # noqa: E402

# `db.<collection>.<operation>(` followed by a filter mentioning user_id,
# within the same statement. Tolerates whitespace and line breaks.
QUERY = re.compile(
    r"db\.(?P<collection>\w+)\s*\.\s*"
    r"(?P<op>find_one|find|update_one|update_many|delete_one|delete_many|count_documents|distinct|aggregate)"
    r"\s*\(\s*(?P<args>.{0,240}?)\)",
    re.DOTALL,
)
USER_ID_FILTER = re.compile(r"[\"']user_id[\"']\s*:")

# Identity and platform collections are legitimately keyed by user_id -- they
# describe a person, not a customer's records.
IDENTITY_COLLECTIONS = {
    "users",
    "user_sessions",
    "invitations",
    "password_reset_tokens",
    "org_members",
    "organisations",
    "audit_log",
}


def _line_of(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


def _violations() -> list[str]:
    source = SERVER.read_text(encoding="utf-8")
    found = []
    for match in QUERY.finditer(source):
        collection = match.group("collection")
        if collection not in ORG_COLLECTIONS or collection in IDENTITY_COLLECTIONS:
            continue
        args = match.group("args")
        if not USER_ID_FILTER.search(args):
            continue
        # A user_id clause is fine when it sits *alongside* an org filter --
        # e.g. narrowing a tenant's records to one author.
        if "org_id" in args or "tenant_filter" in args:
            continue
        line = _line_of(source, match.start())
        snippet = " ".join(match.group(0).split())[:110]
        found.append(f"  server.py:{line}  db.{collection}.{match.group('op')}(...)\n      {snippet}")
    return found


def test_no_raw_user_id_filters_on_tenant_collections():
    violations = _violations()
    if violations:
        pytest.fail(
            "Tenant collections must be scoped by org_id, not user_id.\n\n"
            "Each query below isolates a single user instead of the organisation, so\n"
            "colleagues sharing a fleet would not see each other's records -- and a\n"
            "missing clause would expose another customer's data entirely.\n\n"
            "Use tenancy.tenant_filter(user) instead:\n"
            '    db.vehicles.find(tenant_filter(user))\n'
            '    db.alerts.find(tenant_filter(user, read=False))\n\n'
            + "\n".join(violations),
        )


def test_every_org_collection_is_known():
    """ORG_COLLECTIONS must cover every collection server.py touches.

    A collection added to a route but missing from ORG_COLLECTIONS would be
    skipped by the backfill migration and ignored by this guard -- silently
    unscoped. Catch it here instead.
    """
    source = SERVER.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\bdb\.(\w+)\b", source))
    unknown = referenced - set(ORG_COLLECTIONS) - IDENTITY_COLLECTIONS
    assert not unknown, (
        "server.py uses collections that are neither tenant-scoped nor known "
        "identity collections:\n  "
        + "\n  ".join(sorted(unknown))
        + "\n\nAdd each to tenancy.ORG_COLLECTIONS (tenant data, gets org_id and is "
          "swept by the backfill) or to IDENTITY_COLLECTIONS in this test "
          "(platform/identity records, legitimately keyed by user_id)."
    )
