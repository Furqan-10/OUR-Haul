"""Backfill the organisation layer.

Introduces `organisations` and `org_members`, then stamps `org_id` onto every
existing tenant document.

The mapping preserves today's isolation exactly: **each existing user becomes
the owner of their own single-member organisation.** Nothing is merged. An
operator invited through the old `_seed_template()` flow already had a separate
account with separate data, and they keep it — they simply become the owner of
their own org instead of a lone user_id. No customer sees anything they could
not see before this ran.

Safety properties:

* **Idempotent.** Only documents with no `org_id` are touched, so a partial run
  can simply be repeated.
* **Dry-run first.** `--dry-run` reports exactly what would change and writes
  nothing. Run it, read the counts, then run for real.
* **Orphans are never guessed.** A document whose `user_id` matches no user is
  reported and left alone. Assigning it to an org by inference is how data
  leaks between tenants; leaving it unstamped makes it invisible instead, which
  is the safe failure.

Re-run it whenever a collection is added to `tenancy.ORG_COLLECTIONS`. The loop
reads that tuple rather than a fixed list, and only touches documents with no
`org_id`, so a second run backfills the newly-declared collections and leaves
everything already stamped alone. That is how `repairs`, `recalls` and
`licence_checks` were brought in when Emergent iterations 30-32 merged: they
arrived scoped by `user_id`, which is the shape this migration already handles.

Usage (from backend/, with the venv active):

    python migrations/001_org_layer.py --dry-run
    python migrations/001_org_layer.py
    python migrations/001_org_layer.py --verify
"""
import argparse
import asyncio
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tenancy import ORG_COLLECTIONS, ROLE_OWNER  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def org_name_for(user: dict) -> str:
    """Best available human label for the new organisation.

    The operator profile holds the real company name, but it lives in a
    separate collection; the caller passes it in when present. Falling back to
    the user's own name keeps the admin console readable either way.
    """
    return (user.get("name") or user.get("email", "").split("@")[0] or "Organisation").strip()


async def ensure_orgs(db, dry_run: bool) -> tuple[dict, Counter]:
    """Create one organisation per user. Returns (user_id -> org_id, counts)."""
    counts = Counter()
    mapping: dict[str, str] = {}

    async for user in db.users.find({}, {"_id": 0}):
        uid = user.get("user_id")
        if not uid:
            counts["users_without_id"] += 1
            continue

        existing = await db.organisations.find_one({"owner_user_id": uid}, {"_id": 0})
        if user.get("org_id"):
            mapping[uid] = user["org_id"]
            counts["users_already_mapped"] += 1
            continue
        if existing:
            mapping[uid] = existing["org_id"]
            counts["orgs_reused"] += 1
            if not dry_run:
                await db.users.update_one({"user_id": uid}, {"$set": {"org_id": existing["org_id"]}})
            continue

        org_id = f"org_{uuid.uuid4().hex[:12]}"
        mapping[uid] = org_id
        counts["orgs_created"] += 1
        if dry_run:
            continue

        # The company name lives on the operator profile, keyed by the old
        # user_id scope; prefer it over the person's own name.
        operator = await db.operator.find_one({"user_id": uid}, {"_id": 0}) or {}
        await db.organisations.insert_one({
            "org_id": org_id,
            "name": (operator.get("company_name") or "").strip() or org_name_for(user),
            "owner_user_id": uid,
            # Region moves off the user and onto the org: it is a property of
            # the operating company (UK/DVSA vs IE/RSA), not of a person.
            "region": user.get("region", "UK"),
            # Reserved for the later billing phase. Written now so adding
            # subscriptions needs no second migration. Nothing enforces these.
            "plan": "free",
            "plan_limits": {},
            "subscription_status": "none",
            "active": user.get("active", True),
            "created_at": user.get("created_at") or now_iso(),
            "migrated_at": now_iso(),
        })
        await db.org_members.update_one(
            {"org_id": org_id, "user_id": uid},
            {"$set": {"org_id": org_id, "user_id": uid, "role": ROLE_OWNER,
                      "joined_at": user.get("created_at") or now_iso()}},
            upsert=True,
        )
        await db.users.update_one({"user_id": uid}, {"$set": {"org_id": org_id}})

    return mapping, counts


async def backfill_collections(db, mapping: dict, dry_run: bool) -> tuple[Counter, Counter]:
    """Stamp org_id across every tenant collection."""
    stamped = Counter()
    orphans = Counter()

    for name in ORG_COLLECTIONS:
        coll = db[name]
        pending = await coll.count_documents({"org_id": {"$exists": False}})
        if not pending:
            continue

        # Group by user_id so each distinct owner is one bulk update rather
        # than one update per document.
        owners = await coll.distinct("user_id", {"org_id": {"$exists": False}})
        for uid in owners:
            org_id = mapping.get(uid)
            if not org_id:
                n = await coll.count_documents({"user_id": uid, "org_id": {"$exists": False}})
                orphans[f"{name}:{uid or '<missing user_id>'}"] = n
                continue
            if dry_run:
                stamped[name] += await coll.count_documents(
                    {"user_id": uid, "org_id": {"$exists": False}})
                continue
            res = await coll.update_many(
                {"user_id": uid, "org_id": {"$exists": False}},
                {"$set": {"org_id": org_id}},
            )
            stamped[name] += res.modified_count

    return stamped, orphans


async def verify(db) -> int:
    """Report anything still unscoped. Exit code doubles as a CI gate."""
    print("\nVerification")
    print("-" * 60)
    problems = 0

    users_without_org = await db.users.count_documents({"org_id": {"$exists": False}})
    print(f"{'users missing org_id':<42} {users_without_org:>8}")
    problems += users_without_org

    for name in ORG_COLLECTIONS:
        missing = await db[name].count_documents({"org_id": {"$exists": False}})
        total = await db[name].count_documents({})
        flag = "  <-- UNSCOPED" if missing else ""
        if total or missing:
            print(f"{name:<42} {missing:>8} / {total}{flag}")
        problems += missing

    orgs = await db.organisations.count_documents({})
    members = await db.org_members.count_documents({})
    print("-" * 60)
    print(f"organisations: {orgs}   memberships: {members}")
    print("PASS: every document is org-scoped" if problems == 0
          else f"FAIL: {problems} document(s) still unscoped")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    parser.add_argument("--verify", action="store_true",
                        help="only check for unscoped documents")
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set (see backend/.env.example)")
        return 2

    db = AsyncIOMotorClient(mongo_url)[db_name]
    print(f"Database: {db_name} @ {mongo_url}")

    if args.verify:
        return 1 if await verify(db) else 0

    mode = "DRY RUN -- nothing will be written" if args.dry_run else "APPLYING CHANGES"
    print(f"Mode: {mode}\n")

    mapping, org_counts = await ensure_orgs(db, args.dry_run)
    print("Organisations")
    print("-" * 60)
    for key, value in sorted(org_counts.items()):
        print(f"{key:<42} {value:>8}")
    print(f"{'users mapped to an org':<42} {len(mapping):>8}")

    stamped, orphans = await backfill_collections(db, mapping, args.dry_run)
    print("\nDocuments stamped with org_id")
    print("-" * 60)
    for name in ORG_COLLECTIONS:
        if stamped.get(name):
            print(f"{name:<42} {stamped[name]:>8}")
    print(f"{'TOTAL':<42} {sum(stamped.values()):>8}")

    if orphans:
        print("\nOrphaned documents -- LEFT UNTOUCHED (user_id matches no user)")
        print("-" * 60)
        for key, value in sorted(orphans.items()):
            print(f"{key:<42} {value:>8}")
        print("\nThese are invisible to the app until assigned deliberately.")
        print("Guessing an owner would risk exposing them to the wrong tenant.")

    if args.dry_run:
        print("\nDry run complete. Re-run without --dry-run to apply.")
    else:
        return 1 if await verify(db) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
