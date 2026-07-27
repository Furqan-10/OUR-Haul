"""Organisation scoping — the single source of truth for tenant isolation.

Before this module, "tenant" meant "one individual user": every collection was
filtered by `user_id`, and an invited colleague received their own empty
account rather than access to a shared fleet. That is not workable for a
haulage firm where several staff share one vehicle list.

The unit of tenancy is now the **organisation**. `user_id` is retained on every
document as authorship ("who created this"), but it is no longer what isolates
one customer from another — `org_id` is.

The rule that makes this safe: **no route may build an org filter by hand.**
Every read and write goes through `tenant_filter()` / `stamp()` below, so there
is exactly one line in the codebase that decides what a tenant can see. A
regression test (tests/test_tenancy_guard.py) fails the build if a raw
`{"user_id": user.user_id}` filter reappears in a route.
"""
from typing import Any, Mapping, Optional, Union

from fastapi import HTTPException

# Every collection holding customer data. The keys of a tenant's world: if a
# collection is here, it is scoped by org_id and swept by the backfill
# migration. `users`, `user_sessions`, `invitations` and `password_reset_tokens`
# are deliberately absent — they are identity/platform records, not tenant data.
ORG_COLLECTIONS = (
    "vehicles",
    "trailers",
    "drivers",
    "defects",
    "documents",
    "pmi_schedules",
    "pmi_records",
    "service_records",
    "walkaround_checks",
    "weekly_walkarounds",
    "wheel_audits",
    "tacho",
    "tacho_analyses",
    "training",
    "insurance",
    "fuel",
    "links",
    "trade_unions",
    "operator",
    "alerts",
    "dismissed_alerts",
    "calendar_events",
    "compliance_history",
    "reminder_settings",
    "reminder_log",
    "holidays",
    "test_history",
    "files",
    # Added with Emergent iterations 30-32. They arrived scoped by user_id,
    # which is why they are listed here explicitly rather than discovered: the
    # guard below fails the build for any collection server.py touches that is
    # neither declared tenant data nor a known identity record.
    "repairs",
    "recalls",
    "licence_checks",
)

# Organisation roles, least to most privileged.
ROLE_VIEWER = "viewer"
ROLE_MANAGER = "manager"
ROLE_OWNER = "owner"
ROLE_RANK = {ROLE_VIEWER: 0, ROLE_MANAGER: 1, ROLE_OWNER: 2}
DEFAULT_ROLE = ROLE_OWNER

PLATFORM_ROLE_USER = "user"
PLATFORM_ROLE_ADMIN = "platform_admin"

# An actor is either the authenticated manager (a `User` model carrying org_id)
# or a driver document loaded by get_current_driver. Both carry org_id, so both
# can scope a query.
Actor = Union[Mapping[str, Any], Any]


def org_id_of(actor: Actor) -> Optional[str]:
    """Read org_id off a User model or a driver/user document."""
    if actor is None:
        return None
    if isinstance(actor, Mapping):
        return actor.get("org_id") or None
    return getattr(actor, "org_id", None) or None


def tenant_filter(actor: Actor, **extra: Any) -> dict:
    """The org scope for a query. The only place an org filter is constructed.

    Pass additional criteria as keyword arguments rather than merging a dict
    afterwards, so the org clause can never be accidentally overwritten:

        db.alerts.find(tenant_filter(user, read=False))

    Raises rather than returning an unscoped filter when org_id is missing. An
    unscoped query would read across every customer, so failing the request is
    always the correct outcome.
    """
    oid = org_id_of(actor)
    if not oid:
        raise HTTPException(
            status_code=500,
            detail="Organisation context missing; refusing to run an unscoped query",
        )
    if "org_id" in extra:
        raise HTTPException(status_code=500, detail="org_id may not be overridden")
    return {"org_id": oid, **extra}


def stamp(actor: Actor, payload: dict) -> dict:
    """Stamp ownership onto a document about to be written.

    Sets org_id (the tenant key) and, when the actor is a user, records
    user_id as the author. Mutates and returns `payload` so it can be used
    inline at a call site.
    """
    payload["org_id"] = tenant_filter(actor)["org_id"]
    uid = (
        actor.get("user_id")
        if isinstance(actor, Mapping)
        else getattr(actor, "user_id", None)
    )
    if uid and not payload.get("user_id"):
        payload["user_id"] = uid
    return payload


def role_of(actor: Actor) -> str:
    if isinstance(actor, Mapping):
        return actor.get("org_role") or DEFAULT_ROLE
    return getattr(actor, "org_role", None) or DEFAULT_ROLE


def has_role(actor: Actor, minimum: str) -> bool:
    return ROLE_RANK.get(role_of(actor), -1) >= ROLE_RANK.get(minimum, 99)


def is_platform_admin(actor: Actor) -> bool:
    if isinstance(actor, Mapping):
        value = actor.get("platform_role")
    else:
        value = getattr(actor, "platform_role", None)
    return value == PLATFORM_ROLE_ADMIN


def require_role(minimum: str):
    """FastAPI dependency factory enforcing a minimum organisation role.

        @api_router.delete("/vehicles/{vid}")
        async def delete_vehicle(vid: str, user=Depends(require_role(ROLE_MANAGER))):

    Deliberately independent of `is_platform_admin`: a platform admin acting
    through impersonation is bound by the impersonated org's role, so support
    access cannot silently escalate.
    """
    from fastapi import Depends  # local import keeps this module framework-light

    async def _guard(user=Depends(_current_user_dependency())):
        if not has_role(user, minimum):
            raise HTTPException(
                status_code=403,
                detail=f"This action requires the {minimum} role",
            )
        return user

    return _guard


# server.py registers its `get_current_user` here at import time. This keeps
# tenancy.py free of a circular import back into server.py while still letting
# require_role() depend on the real authentication dependency.
_CURRENT_USER_DEPENDENCY = None


def register_current_user_dependency(dependency) -> None:
    global _CURRENT_USER_DEPENDENCY
    _CURRENT_USER_DEPENDENCY = dependency


def _current_user_dependency():
    if _CURRENT_USER_DEPENDENCY is None:
        raise RuntimeError(
            "register_current_user_dependency() must be called during startup"
        )
    return _CURRENT_USER_DEPENDENCY
