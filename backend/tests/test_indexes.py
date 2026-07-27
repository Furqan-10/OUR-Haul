"""Database indexes must exist, and the hot queries must actually use them.

The application shipped with no indexes at all. That is invisible with one
customer's data and becomes the dominant cost as tenants are added: listing one
org's vehicles had to read every vehicle belonging to every customer.

These tests talk to MongoDB directly rather than over HTTP -- an index is a
property of the database, and `explain()` is the only way to prove a query plan
rather than assume it.
"""
import os
import sys
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import indexes as index_spec  # noqa: E402


@pytest.fixture(scope="module")
def db():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not os.environ.get("MONGO_URL"):
        pytest.skip("MONGO_URL not configured")
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _plan_stage(db, collection: str, filt: dict) -> tuple:
    """(winning stage, documents examined) for a query."""
    plan = db.command("explain", {"find": collection, "filter": filt},
                      verbosity="executionStats")
    stage = plan["queryPlanner"]["winningPlan"]
    while "inputStage" in stage:
        stage = stage["inputStage"]
    return stage.get("stage"), plan["executionStats"]["totalDocsExamined"]


class TestIndexesExist:
    def test_every_declared_index_is_present(self, db):
        """The declared spec and the database agree."""
        missing = []
        for collection, keys, _options in index_spec.INDEX_SPEC:
            existing = db[collection].index_information()
            wanted = [(f, d) for f, d in keys]
            if not any(list(info["key"]) == wanted for info in existing.values()):
                missing.append(f"{collection}({', '.join(f for f, _ in keys)})")
        assert not missing, (
            "Indexes are declared but not present in the database:\n  "
            + "\n  ".join(missing)
            + "\n\nThey are created at startup by indexes.ensure_indexes(); "
              "restart the API, or check the startup log for creation failures."
        )

    def test_tenant_collections_are_indexed_on_org_id(self, db):
        """org_id must lead an index on every collection holding tenant data.

        A compound index is only usable left to right, so an index that does not
        *start* with org_id cannot serve the tenant filter that every query
        applies.
        """
        import tenancy
        unindexed = []
        for collection in tenancy.ORG_COLLECTIONS:
            leads = [list(info["key"])[0][0] for info in
                     db[collection].index_information().values()
                     if info.get("key")]
            if "org_id" not in leads:
                unindexed.append(collection)
        assert not unindexed, (
            "These tenant collections have no index led by org_id, so every "
            "query against them scans the whole collection across all "
            f"customers:\n  {unindexed}"
        )


class TestHotQueriesUseIndexes:
    """The queries on the request path for a normal page load."""

    @pytest.mark.parametrize("collection,filt", [
        ("users", {"email": "someone@example.com"}),          # every login
        ("user_sessions", {"session_token": "x"}),            # every cookie request
        ("organisations", {"org_id": "org_x"}),               # every request
        ("org_members", {"org_id": "org_x", "user_id": "u"}), # every request
        ("drivers", {"access_code": "ABC123"}),               # every driver login
        ("vehicles", {"org_id": "org_x"}),
        ("drivers", {"org_id": "org_x"}),
        ("defects", {"org_id": "org_x"}),
        ("pmi_schedules", {"org_id": "org_x"}),
        ("alerts", {"org_id": "org_x", "read": False}),       # unread badge, polls 60s
    ])
    def test_query_plan_is_an_index_scan(self, db, collection, filt):
        stage, _examined = _plan_stage(db, collection, filt)
        assert stage == "IXSCAN", (
            f"{collection}.find({filt}) uses {stage}, not an index scan. "
            f"This reads every document in the collection -- including other "
            f"customers' -- on every call."
        )

    def test_driver_access_code_lookup_is_indexed(self, db):
        """Driver login matches a code across the whole platform.

        Without an index this scans every driver of every customer on each
        attempt, which is both slow and a denial-of-service lever.
        """
        stage, _ = _plan_stage(db, "drivers", {"access_code": "ZZZZZZ"})
        assert stage == "IXSCAN"


class TestUniquenessConstraints:
    def test_duplicate_email_is_rejected_by_the_database(self, db):
        """Registration checks for an existing address then inserts.

        Two concurrent requests can both pass that check, so the only place the
        race can actually be closed is a unique index.
        """
        email = "test_uniqueness_probe@haulcheck-test.co.uk"
        db.users.delete_many({"email": email})
        db.users.insert_one({"user_id": "test_uniq_1", "email": email})
        try:
            with pytest.raises(DuplicateKeyError):
                db.users.insert_one({"user_id": "test_uniq_2", "email": email})
        finally:
            db.users.delete_many({"email": email})

    def test_no_duplicate_emails_exist(self, db):
        """Duplicates mean two people can sign in to what should be one account."""
        dupes = list(db.users.aggregate([
            {"$group": {"_id": "$email", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]))
        assert not dupes, f"duplicate email addresses in users: {[d['_id'] for d in dupes[:5]]}"

    def test_one_membership_row_per_person_per_org(self, db):
        email_idx = db.org_members.index_information()
        has_unique = any(
            info.get("unique") and [k for k, _ in info["key"]] == ["org_id", "user_id"]
            for info in email_idx.values()
        )
        assert has_unique, "org_members needs a unique (org_id, user_id) index"
