"""Run scheduled jobs exactly once across however many replicas are deployed.

The reminder jobs run in-process on an APScheduler instance started with the
app. That is correct for a single process and wrong the moment the service is
scaled: with N replicas every job fires N times, and these jobs *send email to
customers*. Three replicas meant three copies of every compliance reminder --
the kind of bug that is invisible in staging and immediately visible to the
people paying for the product.

The lock is a single MongoDB document per job, claimed with an atomic
`find_one_and_update`. Whichever replica wins the update runs the job; the rest
see the lock is held and skip. No extra infrastructure -- the database the app
already depends on is the coordination point.

Locks carry an expiry so a replica that dies mid-job does not block the next
run forever, and the holder's identity so the log can say which one has it.
"""
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# Identifies this process in the lock document. The pid distinguishes replicas
# that share a hostname (containers on one node).
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


async def ensure_indexes(db) -> None:
    await db.job_locks.create_index("job", unique=True)


async def acquire(db, job: str, ttl_seconds: int = 3600) -> bool:
    """Try to claim `job`. True if this process should run it.

    Atomic: the filter matches only when the job is unheld or its lease has
    expired, so exactly one concurrent caller can succeed.
    """
    now = datetime.now(timezone.utc)
    try:
        result = await db.job_locks.find_one_and_update(
            {"job": job, "$or": [{"expires_at": {"$lt": now}}, {"expires_at": None}]},
            {"$set": {"job": job, "holder": INSTANCE_ID, "acquired_at": now,
                      "expires_at": now + timedelta(seconds=ttl_seconds)}},
            upsert=True,
            return_document=True,
        )
        return bool(result and result.get("holder") == INSTANCE_ID)
    except Exception as e:
        # A duplicate-key error is the *expected* outcome when another replica
        # claimed the job between this filter and the upsert -- it means someone
        # else is running it, which is exactly what the lock is for.
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            return False
        logging.error(f"Job lock '{job}' could not be evaluated: {e}")
        # Fail closed. Skipping a reminder run is recoverable; sending every
        # customer duplicate emails is not.
        return False


async def release(db, job: str) -> None:
    """Release a lock this process holds, so a retry can run promptly."""
    try:
        await db.job_locks.update_one(
            {"job": job, "holder": INSTANCE_ID},
            {"$set": {"expires_at": datetime.now(timezone.utc)}})
    except Exception as e:
        logging.error(f"Job lock '{job}' release failed: {e}")


def run_once(db_getter, job: str, ttl_seconds: int = 3600):
    """Decorator making a scheduled coroutine single-flight across replicas.

        @run_once(lambda: db, "daily_reminders")
        async def run_daily_reminders(): ...
    """
    def decorate(fn):
        async def wrapper(*args, **kwargs):
            db = db_getter()
            if not await acquire(db, job, ttl_seconds):
                logging.info(f"Job '{job}' is held by another instance; skipping")
                return None
            logging.info(f"Job '{job}' claimed by {INSTANCE_ID}")
            try:
                return await fn(*args, **kwargs)
            finally:
                await release(db, job)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorate
