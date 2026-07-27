"""Database indexes.

The application shipped with **none** beyond MongoDB's automatic `_id`. Every
query was a full collection scan, which is invisible with one customer's data
and becomes the dominant cost as tenants are added: listing one org's vehicles
had to read every vehicle belonging to every customer on the platform.

Two kinds of index are declared here.

**Tenant scoping.** Every query on customer data filters by `org_id`, so that is
the leading field of every compound index. The second field is whatever the
endpoint sorts or filters by next -- a compound index is only usable left to
right, so `(org_id, created_at)` serves "this org's records, newest first" while
`(created_at, org_id)` would not.

**Uniqueness and expiry.** A unique index on `users.email` is a *correctness*
fix, not a performance one: registration checked for an existing address and
then inserted, and two concurrent requests could both pass the check and create
duplicate accounts for the same person. The database is the only place that race
can actually be closed. TTL indexes expire sessions and one-time tokens without
a cleanup job.

Creation is idempotent, so this runs safely on every startup.
"""
import logging
from typing import List, Tuple

import pymongo

# (collection, keys, options)
#
# Keys use pymongo's (field, direction) form. ASCENDING for equality and range
# filters; DESCENDING where the endpoint sorts newest-first, so the index can
# satisfy the sort without an in-memory pass.
_ASC, _DESC = pymongo.ASCENDING, pymongo.DESCENDING

INDEX_SPEC: List[Tuple[str, list, dict]] = [
    # ---- Identity and tenancy ----
    # Unique: closes the duplicate-registration race described above.
    ("users", [("email", _ASC)], {"unique": True, "name": "uniq_email"}),
    ("users", [("org_id", _ASC)], {}),
    ("users", [("platform_role", _ASC)], {}),          # admin console: list admins
    ("users", [("created_at", _DESC)], {}),            # admin console: newest first

    ("organisations", [("org_id", _ASC)], {"unique": True, "name": "uniq_org_id"}),
    ("organisations", [("owner_user_id", _ASC)], {}),  # ensure_org_for_user lookup
    ("organisations", [("created_at", _DESC)], {}),
    ("organisations", [("active", _ASC)], {}),

    # One membership row per person per org.
    ("org_members", [("org_id", _ASC), ("user_id", _ASC)],
     {"unique": True, "name": "uniq_org_member"}),
    ("org_members", [("user_id", _ASC)], {}),          # "which org am I in?"

    ("user_sessions", [("session_token", _ASC)], {}),  # every cookie-auth request
    ("user_sessions", [("user_id", _ASC)], {}),
    ("invitations", [("token", _ASC)], {"unique": True, "name": "uniq_invite_token"}),
    ("invitations", [("invited_by", _ASC), ("created_at", _DESC)], {}),
    ("invitations", [("email", _ASC)], {}),
    ("password_reset_tokens", [("token", _ASC)], {"unique": True, "name": "uniq_reset_token"}),
    ("email_verification_tokens", [("token", _ASC)],
     {"unique": True, "name": "uniq_verify_token"}),

    # ---- Fleet ----
    ("vehicles", [("org_id", _ASC), ("registration", _ASC)], {}),
    ("vehicles", [("org_id", _ASC), ("id", _ASC)], {}),
    ("trailers", [("org_id", _ASC), ("id", _ASC)], {}),

    # Driver access codes are matched globally at login, so this one is not
    # org-scoped -- it is the index that makes that lookup a seek rather than a
    # scan of every driver on the platform.
    ("drivers", [("access_code", _ASC)], {}),
    ("drivers", [("org_id", _ASC), ("id", _ASC)], {}),
    ("drivers", [("org_id", _ASC), ("name", _ASC)], {}),

    # ---- Maintenance ----
    ("defects", [("org_id", _ASC), ("status", _ASC)], {}),
    ("defects", [("org_id", _ASC), ("id", _ASC)], {}),
    ("pmi_schedules", [("org_id", _ASC), ("id", _ASC)], {}),
    ("pmi_schedules", [("org_id", _ASC), ("next_due", _ASC)], {}),
    ("pmi_records", [("org_id", _ASC), ("pmi_id", _ASC)], {}),
    ("pmi_records", [("org_id", _ASC), ("inspection_date", _DESC)], {}),
    ("service_records", [("org_id", _ASC), ("id", _ASC)], {}),
    ("walkaround_checks", [("org_id", _ASC), ("check_date", _DESC)], {}),
    ("walkaround_checks", [("org_id", _ASC), ("id", _ASC)], {}),
    ("weekly_walkarounds", [("org_id", _ASC), ("vehicle_reg", _ASC), ("week_start", _ASC)], {}),
    ("wheel_audits", [("org_id", _ASC), ("id", _ASC)], {}),

    # ---- Repairs and recalls (iterations 30-32) ----
    # The list endpoints sort by date descending, so the sort key is part of the
    # index: without it Mongo reads the org's whole collection and sorts it in
    # memory on every page load.
    ("repairs", [("org_id", _ASC), ("repair_date", _DESC)], {}),
    ("repairs", [("org_id", _ASC), ("id", _ASC)], {}),
    ("recalls", [("org_id", _ASC), ("created_at", _DESC)], {}),
    ("recalls", [("org_id", _ASC), ("id", _ASC)], {}),

    # ---- Tacho ----
    ("tacho", [("org_id", _ASC), ("next_due", _ASC)], {}),
    ("tacho", [("org_id", _ASC), ("id", _ASC)], {}),
    ("tacho_analyses", [("org_id", _ASC), ("created_at", _DESC)], {}),

    # ---- Office ----
    ("documents", [("org_id", _ASC), ("doc_type", _ASC)], {}),
    ("documents", [("org_id", _ASC), ("id", _ASC)], {}),
    ("documents", [("org_id", _ASC), ("driver_id", _ASC)], {}),
    ("training", [("org_id", _ASC), ("expiry_date", _ASC)], {}),
    ("training", [("org_id", _ASC), ("driver_id", _ASC)], {}),
    ("insurance", [("org_id", _ASC), ("policy_type", _ASC)], {}),
    ("fuel", [("org_id", _ASC), ("fill_date", _DESC)], {}),
    ("links", [("org_id", _ASC)], {}),
    ("trade_unions", [("org_id", _ASC), ("id", _ASC)], {}),
    ("operator", [("org_id", _ASC)], {}),
    ("test_history", [("org_id", _ASC), ("id", _ASC)], {}),
    ("holidays", [("org_id", _ASC)], {}),
    # Licence checks are read per driver to rebuild that driver's headline
    # fields, and listed newest-first, so both accesses are served here.
    ("licence_checks", [("org_id", _ASC), ("driver_id", _ASC), ("check_date", _DESC)], {}),
    ("licence_checks", [("org_id", _ASC), ("id", _ASC)], {}),

    # ---- Dashboard, alerts, calendar ----
    # Partial index: the unread badge polls every 60s and only ever asks for
    # unread rows, so indexing only those keeps it small and hot.
    ("alerts", [("org_id", _ASC), ("read", _ASC), ("created_at", _DESC)], {}),
    ("alerts", [("org_id", _ASC), ("id", _ASC)], {}),
    ("dismissed_alerts", [("org_id", _ASC)], {}),
    ("calendar_events", [("org_id", _ASC), ("date", _ASC)], {}),
    ("compliance_history", [("org_id", _ASC), ("date", _ASC)], {}),
    ("reminder_settings", [("org_id", _ASC)], {}),
    ("reminder_log", [("org_id", _ASC)], {}),

    # ---- Files ----
    ("files", [("org_id", _ASC), ("id", _ASC), ("is_deleted", _ASC)], {}),
    ("files", [("id", _ASC)], {}),
]

# Documents that should disappear on their own. expireAfterSeconds=0 means
# "expire at the time stored in this field".
TTL_SPEC: List[Tuple[str, str, int]] = [
    ("auth_attempts", "expires_at", 0),
]


async def ensure_indexes(db) -> dict:
    """Create every declared index. Idempotent; safe on each startup.

    Failures are collected and returned rather than raised: a single index that
    cannot be built (most often a unique index blocked by pre-existing duplicate
    data) must not stop the application from serving.
    """
    created, failed = 0, {}

    for collection, keys, options in INDEX_SPEC:
        try:
            await db[collection].create_index(keys, background=True, **options)
            created += 1
        except Exception as e:
            key_desc = ",".join(k for k, _ in keys)
            failed[f"{collection}({key_desc})"] = str(e)
            logging.error(f"Index {collection}({key_desc}) failed: {e}")

    for collection, field, after in TTL_SPEC:
        try:
            await db[collection].create_index(field, expireAfterSeconds=after, background=True)
            created += 1
        except Exception as e:
            failed[f"{collection}({field} TTL)"] = str(e)

    if failed:
        logging.warning(f"{len(failed)} index(es) could not be created: {list(failed)}")
    return {"created": created, "failed": failed}


async def find_duplicate_emails(db) -> list:
    """Addresses held by more than one account.

    The unique index on `users.email` cannot be built while duplicates exist,
    and duplicates mean two people can log in to what should be one account.
    Reported rather than merged automatically -- deciding which record is
    authoritative is not a decision to make silently.
    """
    pipeline = [
        {"$group": {"_id": "$email", "count": {"$sum": 1},
                    "user_ids": {"$push": "$user_id"}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
    ]
    return await db.users.aggregate(pipeline).to_list(200)
