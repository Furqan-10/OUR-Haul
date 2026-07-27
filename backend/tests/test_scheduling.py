"""Scheduled jobs must run once across all replicas, not once per replica.

The reminder jobs send email to customers. Run in-process on every replica --
which is what an unguarded APScheduler does -- three replicas send three copies
of every compliance reminder. That is invisible in a single-process staging
environment and immediately visible to the people paying for the product.

These tests exercise the lock directly with concurrent callers, because the
failure only appears under concurrency.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scheduling  # noqa: E402


def _db():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not os.environ.get("MONGO_URL"):
        pytest.skip("MONGO_URL not configured")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def job_name():
    return f"test_job_{uuid.uuid4().hex[:8]}"


def test_only_one_caller_acquires_the_lock(job_name):
    async def run():
        db = _db()
        await scheduling.ensure_indexes(db)
        try:
            # Ten replicas reaching the same cron tick simultaneously.
            results = await asyncio.gather(*[
                scheduling.acquire(db, job_name) for _ in range(10)
            ])
            assert sum(1 for r in results if r) == 1, (
                f"{sum(1 for r in results if r)} instances acquired the lock; "
                f"exactly one must. Every winner sends a full round of "
                f"reminder emails to every customer."
            )
        finally:
            await db.job_locks.delete_one({"job": job_name})
    asyncio.run(run())


def test_a_held_lock_blocks_later_callers(job_name):
    async def run():
        db = _db()
        try:
            assert await scheduling.acquire(db, job_name) is True
            assert await scheduling.acquire(db, job_name) is False
        finally:
            await db.job_locks.delete_one({"job": job_name})
    asyncio.run(run())


def test_releasing_allows_the_next_run(job_name):
    async def run():
        db = _db()
        try:
            assert await scheduling.acquire(db, job_name) is True
            await scheduling.release(db, job_name)
            # A retry after a completed run must not be blocked by the
            # previous holder's lease.
            assert await scheduling.acquire(db, job_name) is True
        finally:
            await db.job_locks.delete_one({"job": job_name})
    asyncio.run(run())


def test_an_expired_lease_is_reclaimed(job_name):
    """A replica that dies mid-job must not block the schedule forever."""
    async def run():
        db = _db()
        try:
            assert await scheduling.acquire(db, job_name, ttl_seconds=-1) is True
            # The lease is already in the past, so the next tick may take it.
            assert await scheduling.acquire(db, job_name) is True
        finally:
            await db.job_locks.delete_one({"job": job_name})
    asyncio.run(run())


def test_decorated_job_body_runs_exactly_once(job_name):
    """The decorator, not just the primitive, must be single-flight."""
    async def run():
        db = _db()
        calls = []

        @scheduling.run_once(lambda: db, job_name)
        async def send_reminders():
            calls.append(1)
            return "sent"

        try:
            # Sequential calls: the decorator releases on completion, so both
            # run. What must never happen is two *concurrent* bodies.
            results = await asyncio.gather(send_reminders(), send_reminders(),
                                           send_reminders())
            ran = [r for r in results if r == "sent"]
            assert len(ran) == 1, (
                f"{len(ran)} concurrent runs executed the job body; "
                f"exactly one must."
            )
            assert len(calls) == 1
        finally:
            await db.job_locks.delete_one({"job": job_name})
    asyncio.run(run())
