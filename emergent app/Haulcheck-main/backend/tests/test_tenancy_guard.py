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
_OPS = (r"find_one|find|update_one|update_many|delete_one|delete_many"
        r"|count_documents|distinct|aggregate")

# `db[<expr>].<operation>(` -- the collection chosen at runtime, as the records
# retention and report-builder endpoints do when they loop over a table of
# collection names.
#
# This exists because the pattern above cannot see these at all: it requires a
# literal attribute name. Two real cross-tenant reads reached the merge through
# exactly that blind spot, in `records_retention`, and the guard reported the
# file clean. The collection is not knowable statically, so there is nothing to
# check against ORG_COLLECTIONS -- any user_id filter reached this way is
# treated as a violation and must use tenant_filter().
DYNAMIC_QUERY = re.compile(
    r"db\[(?P<expr>[^\]\n]{0,60})\]\s*\.\s*"
    r"(?P<op>" + _OPS + r")"
    r"\s*\(\s*(?P<args>.{0,240}?)\)",
    re.DOTALL,
)
USER_ID_FILTER = re.compile(r"[\"']user_id[\"']\s*:")
# Must match org_id used as a *filter key*. Matching the bare substring would
# wave through `{"user_id": org_id}` -- the right value under the wrong key,
# which scopes by person while looking like it scopes by org.
ORG_ID_KEY = re.compile(r"[\"']org_id[\"']\s*:|tenant_filter\s*\(")

# Identity and platform collections are legitimately keyed by user_id -- they
# describe a person, not a customer's records.
IDENTITY_COLLECTIONS = {
    "users",
    "user_sessions",
    "invitations",
    "password_reset_tokens",
    "email_verification_tokens",
    "org_members",
    "organisations",
    # Platform-level records that deliberately span every tenant.
    "audit_log",
    "auth_attempts",
    "job_locks",
    # In-flight OAuth state, consumed once during sign-in -- it exists before
    # any organisation has been resolved.
    "oauth_states",
}


# A deliberate, reviewed exception is marked at the call site rather than
# listed here, so the justification travels with the code:
#
#     # tenancy: allow-user-scope -- runs before the org exists
#     op = await db.operator.find_one({"user_id": uid}, {"_id": 0})
#
# Keeping the escape hatch narrow and visible is the point: a reviewer seeing
# this comment in a diff knows to check the reasoning.
PRAGMA = "tenancy: allow-user-scope"


def _line_of(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


def _is_exempt(source: str, start: int) -> bool:
    """True when the pragma appears on the statement or in the comment block above it.

    Walks back over the contiguous run of comment lines immediately preceding
    the statement, so a multi-line justification works and the pragma does not
    have to be crammed onto one line. Stops at the first non-comment line, which
    keeps an exemption from leaking onto unrelated code further up.
    """
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", start)
    if PRAGMA in source[line_start:line_end if line_end != -1 else len(source)]:
        return True
    lines = source[:line_start].splitlines()
    for line in reversed(lines):
        if not line.strip().startswith("#"):
            return False
        if PRAGMA in line:
            return True
    return False


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
        if ORG_ID_KEY.search(args):
            continue
        if _is_exempt(source, match.start()):
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


def _dynamic_violations() -> list[str]:
    source = SERVER.read_text(encoding="utf-8")
    found = []
    for match in DYNAMIC_QUERY.finditer(source):
        args = match.group("args")
        if not USER_ID_FILTER.search(args) or ORG_ID_KEY.search(args):
            continue
        if _is_exempt(source, match.start()):
            continue
        line = _line_of(source, match.start())
        snippet = " ".join(match.group(0).split())[:110]
        found.append(f"  server.py:{line}  db[{match.group('expr').strip()}]"
                     f".{match.group('op')}(...)\n      {snippet}")
    return found


def test_no_raw_user_id_filters_through_dynamic_collection_access():
    violations = _dynamic_violations()
    if violations:
        pytest.fail(
            "Collections selected at runtime must still be scoped by org_id.\n\n"
            "db[name] hides the collection from the literal-attribute check above,\n"
            "so these queries look clean while reading one person's rows instead of\n"
            "the organisation's -- or, with the clause dropped, every customer's.\n\n"
            "Use tenancy.tenant_filter(user):\n"
            '    db[coll].find(tenant_filter(user))\n\n'
            + "\n".join(violations),
        )


def test_every_org_collection_is_known():
    """ORG_COLLECTIONS must cover every collection server.py touches.

    A collection added to a route but missing from ORG_COLLECTIONS would be
    skipped by the backfill migration and ignored by this guard -- silently
    unscoped. Catch it here instead.
    """
    # Attributes of the Motor/PyMongo database object itself. `db.command(...)`
    # is a driver call, not a collection named "command".
    DRIVER_ATTRS = {
        "command", "client", "name", "list_collection_names", "create_collection",
        "drop_collection", "aggregate", "watch", "get_collection", "with_options",
        "validate_collection", "dereference", "list_collections",
    }
    source = SERVER.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\bdb\.(\w+)\b", source))
    unknown = referenced - set(ORG_COLLECTIONS) - IDENTITY_COLLECTIONS - DRIVER_ATTRS
    assert not unknown, (
        "server.py uses collections that are neither tenant-scoped nor known "
        "identity collections:\n  "
        + "\n  ".join(sorted(unknown))
        + "\n\nAdd each to tenancy.ORG_COLLECTIONS (tenant data, gets org_id and is "
          "swept by the backfill) or to IDENTITY_COLLECTIONS in this test "
          "(platform/identity records, legitimately keyed by user_id)."
    )
