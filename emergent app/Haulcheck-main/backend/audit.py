"""Append-only audit log.

Records who did what, to whom, and when. Two kinds of event share the
collection:

* **Platform events** -- anything an administrator does through /api/admin:
  suspending a tenant, changing a role, starting an impersonation session.
  These are the ones that need to be answerable months later ("who disabled
  this customer, and when?").
* **Tenant events** -- security-relevant actions inside a customer's own
  account: logins, role changes, member removal, deletions.

The log is append-only *by construction*: nothing in the codebase updates or
deletes from `audit_log`, and no route exposes a mutation. That is the whole
value of it -- a log an administrator can quietly edit is not evidence.

Entries are deliberately denormalised (actor email, org name and so on are
copied in at write time) so a record still reads correctly after the accounts
it refers to have been renamed or deleted.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

# Platform-administration actions.
ADMIN_ORG_SUSPEND = "admin.org.suspend"
ADMIN_ORG_REACTIVATE = "admin.org.reactivate"
ADMIN_ORG_DELETE = "admin.org.delete"
ADMIN_USER_SUSPEND = "admin.user.suspend"
ADMIN_USER_REACTIVATE = "admin.user.reactivate"
ADMIN_USER_REVOKE_SESSIONS = "admin.user.revoke_sessions"
ADMIN_IMPERSONATE_START = "admin.impersonate.start"
ADMIN_VIEW_TENANT = "admin.tenant.view"

# Tenant-side security events.
ORG_MEMBER_ROLE_CHANGED = "org.member.role_changed"
ORG_MEMBER_REMOVED = "org.member.removed"
ORG_MEMBER_INVITED = "org.member.invited"


async def record(
    db,
    action: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_email: str = "",
    actor_is_admin: bool = False,
    impersonated_by: Optional[str] = None,
    target_org_id: Optional[str] = None,
    target_org_name: str = "",
    target_user_id: Optional[str] = None,
    target_user_email: str = "",
    before: Any = None,
    after: Any = None,
    ip: str = "",
    detail: str = "",
) -> None:
    """Write one audit entry.

    Never raises. An audit write failing must not also fail the action the user
    asked for -- that would turn a logging outage into an outage of the admin
    console. Failures are logged at error level so they surface in monitoring.
    """
    try:
        await db.audit_log.insert_one({
            "at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "actor_is_admin": actor_is_admin,
            "impersonated_by": impersonated_by,
            "target_org_id": target_org_id,
            "target_org_name": target_org_name,
            "target_user_id": target_user_id,
            "target_user_email": target_user_email,
            "before": before,
            "after": after,
            "ip": ip,
            "detail": detail,
        })
    except Exception as e:  # pragma: no cover - defensive
        logging.error(f"Audit write failed for {action}: {e}")


async def record_for(db, request, user, action: str, **kwargs) -> None:
    """Convenience wrapper that fills the actor fields from an authenticated user."""
    import security  # local import avoids a cycle at module load

    await record(
        db,
        action,
        actor_user_id=getattr(user, "user_id", None),
        actor_email=getattr(user, "email", ""),
        actor_is_admin=getattr(user, "platform_role", "") == "platform_admin",
        impersonated_by=getattr(user, "impersonated_by", None),
        ip=security.client_ip(request) if request is not None else "",
        **kwargs,
    )


async def ensure_indexes(db) -> None:
    """Indexes for the queries the admin console actually runs.

    No TTL here on purpose: audit records are the durable answer to "who did
    this", and expiring them would defeat the point.
    """
    await db.audit_log.create_index([("at", -1)])
    await db.audit_log.create_index([("target_org_id", 1), ("at", -1)])
    await db.audit_log.create_index([("actor_user_id", 1), ("at", -1)])
    await db.audit_log.create_index([("action", 1), ("at", -1)])
