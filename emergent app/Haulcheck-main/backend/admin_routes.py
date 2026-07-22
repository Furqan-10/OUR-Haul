"""Platform administration API (/api/admin).

Operator-level control over the whole platform: every organisation, every user,
usage metrics, the audit log, and support impersonation.

Three rules shape this module:

1. **The role is not grantable through the API.** `platform_role` is set only by
   `scripts/grant_admin.py`, run against the database by someone with server
   access. No request body, registration path or OAuth response can produce an
   administrator, so the console cannot be reached by privilege escalation.

2. **Every state change is audited.** Reads of a specific tenant are logged too,
   because looking at a customer's compliance data is itself an event worth
   being able to account for.

3. **Impersonation is read-only.** A support session can see anything but change
   nothing; the enforcement lives in `server.get_current_user`, and the token is
   short-lived. Being able to *act* as a customer would make the audit trail
   meaningless -- their records would show changes they never made.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import audit
import security
import tenancy

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Wired up by server.py at import time to avoid a circular import.
_db = None
_get_current_user = None
_create_jwt = None
_pwd_context = None


def configure(db, get_current_user, create_jwt, pwd_context) -> None:
    global _db, _get_current_user, _create_jwt, _pwd_context
    _db, _get_current_user, _create_jwt, _pwd_context = db, get_current_user, create_jwt, pwd_context


async def require_platform_admin(request: Request):
    """Guard for every route here.

    Deliberately rejects an impersonated session even if the underlying account
    is an administrator: impersonation exists to view a tenant's world, and
    letting it reach the admin API would allow an escalation loop (impersonate,
    then impersonate someone else) with a muddled audit trail.
    """
    user = await _get_current_user(request)
    if not tenancy.is_platform_admin(user):
        # 404 rather than 403: the admin surface should not confirm it exists to
        # someone who cannot use it.
        raise HTTPException(status_code=404, detail="Not found")
    if user.impersonated_by:
        raise HTTPException(status_code=403,
                            detail="Administration is unavailable during an impersonated session")
    return user


# --------------------------------------------------------------- organisations

@router.get("/organisations")
async def list_organisations(
    q: str = Query("", description="search by organisation or owner email"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    admin=Depends(require_platform_admin),
):
    """Every tenant on the platform, with the counts that describe its size."""
    criteria = {}
    if q:
        owners = await _db.users.find(
            {"email": {"$regex": q, "$options": "i"}}, {"_id": 0, "user_id": 1}).to_list(200)
        criteria = {"$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"org_id": q},
            {"owner_user_id": {"$in": [o["user_id"] for o in owners]}},
        ]}

    total = await _db.organisations.count_documents(criteria)
    orgs = await _db.organisations.find(criteria, {"_id": 0}).sort("created_at", -1) \
        .skip(offset).limit(limit).to_list(limit)

    rows = []
    for org in orgs:
        oid = org["org_id"]
        owner = await _db.users.find_one({"user_id": org.get("owner_user_id")},
                                         {"_id": 0, "email": 1, "name": 1, "last_login_at": 1}) or {}
        rows.append({
            **org,
            "owner_email": owner.get("email", ""),
            "owner_name": owner.get("name", ""),
            "owner_last_login_at": owner.get("last_login_at"),
            "member_count": await _db.org_members.count_documents({"org_id": oid}),
            "vehicle_count": await _db.vehicles.count_documents({"org_id": oid}),
            "driver_count": await _db.drivers.count_documents({"org_id": oid}),
        })
    return {"total": total, "limit": limit, "offset": offset, "organisations": rows}


@router.get("/organisations/{org_id}")
async def get_organisation_detail(org_id: str, request: Request,
                                  admin=Depends(require_platform_admin)):
    org = await _db.organisations.find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    members = await _db.org_members.find({"org_id": org_id}, {"_id": 0}).to_list(200)
    users = await _db.users.find(
        {"user_id": {"$in": [m["user_id"] for m in members]}},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "active": 1,
         "last_login_at": 1, "email_verified": 1},
    ).to_list(200)
    by_id = {u["user_id"]: u for u in users}

    # Record counts per collection: the practical measure of a tenant's usage.
    record_counts = {}
    for name in tenancy.ORG_COLLECTIONS:
        n = await _db[name].count_documents({"org_id": org_id})
        if n:
            record_counts[name] = n

    await audit.record_for(_db, request, admin, audit.ADMIN_VIEW_TENANT,
                           target_org_id=org_id, target_org_name=org.get("name", ""))
    return {
        **org,
        "members": [{**by_id.get(m["user_id"], {}), "role": m.get("role")} for m in members],
        "record_counts": record_counts,
        "total_records": sum(record_counts.values()),
    }


@router.post("/organisations/{org_id}/suspend")
async def suspend_organisation(org_id: str, request: Request, payload: dict = None,
                               admin=Depends(require_platform_admin)):
    """Take a whole tenant offline.

    Members are refused at authentication (`_build_user` checks the org's active
    flag), so this locks out every user and driver in one action.
    """
    org = await _db.organisations.find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    reason = ((payload or {}).get("reason") or "").strip()
    await _db.organisations.update_one({"org_id": org_id}, {"$set": {
        "active": False, "suspended_at": datetime.now(timezone.utc).isoformat(),
        "suspended_reason": reason,
    }})
    # Drop cookie sessions immediately; bearer tokens are refused by the org's
    # active check on the next request.
    member_ids = [m["user_id"] for m in
                  await _db.org_members.find({"org_id": org_id}, {"_id": 0, "user_id": 1}).to_list(500)]
    await _db.user_sessions.delete_many({"user_id": {"$in": member_ids}})

    await audit.record_for(_db, request, admin, audit.ADMIN_ORG_SUSPEND,
                           target_org_id=org_id, target_org_name=org.get("name", ""),
                           before={"active": org.get("active", True)}, after={"active": False},
                           detail=reason)
    return {"ok": True, "active": False}


@router.post("/organisations/{org_id}/reactivate")
async def reactivate_organisation(org_id: str, request: Request,
                                  admin=Depends(require_platform_admin)):
    org = await _db.organisations.find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    await _db.organisations.update_one(
        {"org_id": org_id},
        {"$set": {"active": True}, "$unset": {"suspended_at": "", "suspended_reason": ""}})
    await audit.record_for(_db, request, admin, audit.ADMIN_ORG_REACTIVATE,
                           target_org_id=org_id, target_org_name=org.get("name", ""),
                           before={"active": False}, after={"active": True})
    return {"ok": True, "active": True}


@router.delete("/organisations/{org_id}")
async def delete_organisation(org_id: str, request: Request,
                              confirm_name: str = Query(..., description="must match the org name"),
                              admin=Depends(require_platform_admin)):
    """Permanently delete a tenant and all of its records.

    Requires the organisation's name to be typed back. This destroys statutory
    compliance evidence -- inspection sheets, defect history, tacho records that
    an operator may be legally required to retain -- so a mistyped id must not
    be enough to trigger it.
    """
    org = await _db.organisations.find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    if confirm_name.strip() != (org.get("name") or "").strip():
        raise HTTPException(status_code=400,
                            detail="Confirmation does not match the organisation name")

    deleted = {}
    for name in tenancy.ORG_COLLECTIONS:
        res = await _db[name].delete_many({"org_id": org_id})
        if res.deleted_count:
            deleted[name] = res.deleted_count
    member_ids = [m["user_id"] for m in
                  await _db.org_members.find({"org_id": org_id}, {"_id": 0, "user_id": 1}).to_list(500)]
    await _db.org_members.delete_many({"org_id": org_id})
    await _db.user_sessions.delete_many({"user_id": {"$in": member_ids}})
    # Users are detached rather than deleted: a person may be a member of
    # another organisation, and their identity is not this tenant's property.
    await _db.users.update_many({"user_id": {"$in": member_ids}}, {"$unset": {"org_id": ""}})
    await _db.organisations.delete_one({"org_id": org_id})

    await audit.record_for(_db, request, admin, audit.ADMIN_ORG_DELETE,
                           target_org_id=org_id, target_org_name=org.get("name", ""),
                           before={"records": deleted, "members": len(member_ids)},
                           detail="permanent deletion")
    return {"ok": True, "deleted": deleted, "detached_users": len(member_ids)}


# ----------------------------------------------------------------------- users

@router.get("/users")
async def list_users(q: str = Query(""), limit: int = Query(50, le=200),
                     offset: int = Query(0, ge=0), admin=Depends(require_platform_admin)):
    criteria = {}
    if q:
        criteria = {"$or": [{"email": {"$regex": q, "$options": "i"}},
                            {"name": {"$regex": q, "$options": "i"}},
                            {"user_id": q}]}
    total = await _db.users.count_documents(criteria)
    users = await _db.users.find(
        criteria,
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)

    org_ids = {u.get("org_id") for u in users if u.get("org_id")}
    orgs = await _db.organisations.find({"org_id": {"$in": list(org_ids)}},
                                        {"_id": 0, "org_id": 1, "name": 1, "active": 1}).to_list(200)
    org_by_id = {o["org_id"]: o for o in orgs}
    for u in users:
        org = org_by_id.get(u.get("org_id"), {})
        u["org_name"] = org.get("name", "")
        u["org_active"] = org.get("active", True)
    return {"total": total, "limit": limit, "offset": offset, "users": users}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str, request: Request, admin=Depends(require_platform_admin)):
    target = await _db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "active": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="You cannot suspend your own account")
    # Bumping token_version retires live bearer tokens as well as cookies.
    await _db.users.update_one({"user_id": user_id},
                               {"$set": {"active": False}, "$inc": {"token_version": 1}})
    await _db.user_sessions.delete_many({"user_id": user_id})
    await audit.record_for(_db, request, admin, audit.ADMIN_USER_SUSPEND,
                           target_user_id=user_id, target_user_email=target.get("email", ""),
                           before={"active": target.get("active", True)}, after={"active": False})
    return {"ok": True, "active": False}


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(user_id: str, request: Request, admin=Depends(require_platform_admin)):
    target = await _db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await _db.users.update_one({"user_id": user_id}, {"$set": {"active": True}})
    await audit.record_for(_db, request, admin, audit.ADMIN_USER_REACTIVATE,
                           target_user_id=user_id, target_user_email=target.get("email", ""),
                           before={"active": False}, after={"active": True})
    return {"ok": True, "active": True}


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(user_id: str, request: Request,
                               admin=Depends(require_platform_admin)):
    """Sign a user out everywhere without disabling the account."""
    target = await _db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await _db.users.update_one({"user_id": user_id}, {"$inc": {"token_version": 1}})
    await _db.user_sessions.delete_many({"user_id": user_id})
    await audit.record_for(_db, request, admin, audit.ADMIN_USER_REVOKE_SESSIONS,
                           target_user_id=user_id, target_user_email=target.get("email", ""))
    return {"ok": True}


# --------------------------------------------------------------- impersonation

@router.post("/impersonate/{user_id}")
async def impersonate(user_id: str, request: Request, admin=Depends(require_platform_admin)):
    """Mint a short-lived, read-only token for a customer's account.

    For diagnosing a reported problem in the customer's own view. The token
    lasts an hour, carries `impersonated_by`, and cannot write -- see
    `server.get_current_user`.
    """
    target = await _db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    org = await _db.organisations.find_one({"org_id": target.get("org_id")},
                                           {"_id": 0, "name": 1, "org_id": 1}) or {}
    token = _create_jwt(user_id, target.get("token_version", 0), impersonated_by=admin.user_id)
    await audit.record_for(_db, request, admin, audit.ADMIN_IMPERSONATE_START,
                           target_user_id=user_id, target_user_email=target.get("email", ""),
                           target_org_id=org.get("org_id"), target_org_name=org.get("name", ""),
                           detail="read-only support session, 60 minutes")
    return {
        "token": token,
        "expires_in_minutes": 60,
        "read_only": True,
        "user": {"user_id": user_id, "email": target.get("email"), "name": target.get("name")},
        "organisation": {"org_id": org.get("org_id"), "name": org.get("name")},
    }


# --------------------------------------------------------------------- metrics

@router.get("/metrics")
async def platform_metrics(days: int = Query(30, ge=1, le=365),
                           admin=Depends(require_platform_admin)):
    """Headline numbers for the platform."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()

    total_orgs = await _db.organisations.count_documents({})
    suspended_orgs = await _db.organisations.count_documents({"active": False})
    total_users = await _db.users.count_documents({})
    suspended_users = await _db.users.count_documents({"active": False})
    new_orgs = await _db.organisations.count_documents({"created_at": {"$gte": since}})
    new_users = await _db.users.count_documents({"created_at": {"$gte": since}})
    active_users = await _db.users.count_documents({"last_login_at": {"$gte": since}})

    # Signups per day, for a sparkline.
    signups = {}
    async for u in _db.users.find({"created_at": {"$gte": since}}, {"_id": 0, "created_at": 1}):
        day = (u.get("created_at") or "")[:10]
        if day:
            signups[day] = signups.get(day, 0) + 1

    records = {}
    for name in tenancy.ORG_COLLECTIONS:
        n = await _db[name].count_documents({})
        if n:
            records[name] = n

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "organisations": {"total": total_orgs, "suspended": suspended_orgs,
                          "new_in_window": new_orgs},
        "users": {"total": total_users, "suspended": suspended_users,
                  "new_in_window": new_users, "active_in_window": active_users},
        "records": {"by_collection": records, "total": sum(records.values())},
        "signups_by_day": [{"date": d, "count": c} for d, c in sorted(signups.items())],
        "storage": {"files": await _db.files.count_documents({"is_deleted": False})},
    }


# ------------------------------------------------------------------- audit log

@router.get("/audit-log")
async def read_audit_log(
    action: str = Query(""),
    org_id: str = Query(""),
    actor: str = Query(""),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    admin=Depends(require_platform_admin),
):
    criteria = {}
    if action:
        criteria["action"] = action
    if org_id:
        criteria["target_org_id"] = org_id
    if actor:
        criteria["actor_email"] = {"$regex": actor, "$options": "i"}
    total = await _db.audit_log.count_documents(criteria)
    entries = await _db.audit_log.find(criteria, {"_id": 0}).sort("at", -1) \
        .skip(offset).limit(limit).to_list(limit)
    return {"total": total, "limit": limit, "offset": offset, "entries": entries}
