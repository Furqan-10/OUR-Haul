"""Authentication hardening: rate limiting, lockout, and password policy.

The app was built for a single trusted operator and opened up to public
signup without the controls that implies. Two endpoints could be guessed at
indefinitely:

  * ``POST /api/auth/login`` -- unlimited password attempts.
  * ``POST /api/driver/login`` -- a 6-character access code matched *globally
    across every tenant*, with unlimited attempts and a 30-day token on
    success. 31^6 is ~887 million combinations, but the search space is shared:
    every driver on the platform is a valid answer, so the odds improve with
    every customer added.

Rate limiting is the control that actually closes both. Password length helps
against an offline crack of a stolen database; it does nothing against online
guessing, where only attempt limits matter.

State lives in MongoDB rather than process memory, deliberately: an in-process
counter resets on deploy and is per-worker, so N replicas would multiply the
allowance by N. A TTL index expires the records, so nothing needs cleaning up.
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

# ---------------------------------------------------------------- rate limits

# Two limits per endpoint, with very different jobs.
#
# The *identifier* limit (an email address, an access code) is the tight one: it
# is what an attacker targets, and no legitimate user needs many failed attempts
# against a single account.
#
# The *address* limit is deliberately loose. Whole organisations sit behind one
# public IP -- a transport office where ten staff share a NAT gateway, each
# occasionally mistyping a password, would be locked out en masse by a tight
# per-IP rule. It exists to stop bulk abuse from one host, not to protect an
# individual account.
#
# Sweeping driver codes is the one attack that only the address limit can stop
# (each guess is a different code, so the per-code limit never fires). 30
# attempts per 15 minutes reduces the 31^6 legacy keyspace to millions of years
# of guessing, so it does not need to be tight to be effective.
RATE_LIMITS = {
    # bucket:            (max attempts, window seconds, lockout seconds)
    "login_ip":           (100, 15 * 60, 15 * 60),
    "login_email":        (10, 15 * 60, 15 * 60),
    "driver_login_ip":    (30, 15 * 60, 30 * 60),
    "driver_login_code":  (8, 15 * 60, 30 * 60),
    "forgot_password_ip": (30, 60 * 60, 60 * 60),
    "forgot_password_email": (5, 60 * 60, 60 * 60),
}


def _trust_proxy_headers() -> bool:
    return (os.environ.get("TRUST_PROXY_HEADERS", "") or "").strip().lower() in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    """The client address used for per-IP rate limiting.

    By default this is the real TCP peer (``request.client.host``), which cannot
    be forged. ``X-Forwarded-For`` is honoured ONLY when ``TRUST_PROXY_HEADERS``
    is set, because a client can put anything in that header: trusting it on a
    directly-exposed service would let an attacker rotate the value and sidestep
    the per-IP limit entirely -- the one control that stops a driver-code sweep.

    Set ``TRUST_PROXY_HEADERS=1`` only when the app sits behind a proxy that
    overwrites the header (nginx, a cloud load balancer). The left-most entry is
    the originating client in that arrangement.
    """
    if _trust_proxy_headers():
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hash_key(value: str) -> str:
    """Store a digest rather than the raw identifier.

    The key can be an email address or a driver's access code -- a live
    credential. Hashing keeps the rate-limit collection from becoming a
    directory of valid codes if it is ever dumped.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def ensure_indexes(db) -> None:
    """TTL index so attempt records expire without a cleanup job."""
    await db.auth_attempts.create_index("expires_at", expireAfterSeconds=0)
    await db.auth_attempts.create_index([("bucket", 1), ("key", 1)])


async def check_rate_limit(db, bucket: str, identifier: str) -> None:
    """Raise 429 if this identifier is currently locked out.

    Called *before* verifying a credential, so a locked-out attacker cannot
    even reach the comparison.
    """
    max_attempts, window, lockout = RATE_LIMITS.get(bucket, (10, 900, 900))
    now = datetime.now(timezone.utc)
    rec = await db.auth_attempts.find_one({"bucket": bucket, "key": _hash_key(identifier)})
    if not rec:
        return

    locked_until = rec.get("locked_until")
    if locked_until:
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            retry = int((locked_until - now).total_seconds())
            raise HTTPException(
                status_code=429,
                detail=f"Too many attempts. Try again in {max(1, retry // 60)} minute(s).",
                headers={"Retry-After": str(retry)},
            )
    return


async def record_failure(db, bucket: str, identifier: str) -> None:
    """Count a failed attempt and lock out once the threshold is crossed."""
    max_attempts, window, lockout = RATE_LIMITS.get(bucket, (10, 900, 900))
    now = datetime.now(timezone.utc)
    key = _hash_key(identifier)

    rec = await db.auth_attempts.find_one({"bucket": bucket, "key": key})
    window_start = now - timedelta(seconds=window)
    count = 1
    if rec:
        first = rec.get("first_attempt_at")
        if isinstance(first, str):
            first = datetime.fromisoformat(first)
        if first and first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        # Attempts older than the window do not count towards a lockout.
        count = (rec.get("count", 0) + 1) if first and first > window_start else 1

    update = {
        "bucket": bucket,
        "key": key,
        "count": count,
        "last_attempt_at": now,
        "expires_at": now + timedelta(seconds=max(window, lockout) + 60),
    }
    if count == 1:
        update["first_attempt_at"] = now
    if count >= max_attempts:
        update["locked_until"] = now + timedelta(seconds=lockout)

    await db.auth_attempts.update_one({"bucket": bucket, "key": key},
                                      {"$set": update}, upsert=True)


async def clear_failures(db, bucket: str, identifier: str) -> None:
    """Reset the counter after a successful authentication."""
    await db.auth_attempts.delete_one({"bucket": bucket, "key": _hash_key(identifier)})


# ------------------------------------------------------------ password policy

MIN_PASSWORD_LENGTH = 12

# Substrings that make a password guessable regardless of its length. Matched
# case-insensitively against the whole password, so "Password123!" is refused
# on the strength of "password" alone. Not a complete list -- it is the cheap
# defence; rate limiting is the real one.
_WEAK_PATTERNS = (
    "password", "passw0rd", "haulcheck", "qwerty", "letmein", "welcome",
    "admin", "iloveyou", "monkey", "dragon", "football", "abc123",
    "123456", "654321", "111111", "000000", "changeme", "secret",
)


def password_problem(password: str, *, email: str = "", name: str = "") -> Optional[str]:
    """Return a human-readable reason the password is unacceptable, or None.

    Follows NIST SP 800-63B in spirit: length and a blocklist of known-weak
    values, rather than composition rules (which push people towards
    "Password1!" -- long enough to pass, trivial to guess).
    """
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > 200:
        return "Password must be 200 characters or fewer"

    lowered = password.lower()
    for pattern in _WEAK_PATTERNS:
        if pattern in lowered:
            return "That password is too easy to guess. Choose something less common."

    # A long string of one repeated character clears the length bar but not much else.
    if len(set(password)) < 5:
        return "Password must use a wider variety of characters"

    # Sequential runs ("abcdefghijkl", "123456789012").
    if re.search(r"(?:0123456789|abcdefghij|qwertyuiop)", lowered):
        return "That password is too easy to guess. Choose something less common."

    local_part = (email or "").split("@")[0].lower()
    if local_part and len(local_part) >= 4 and local_part in lowered:
        return "Password must not contain your email address"
    if name and len(name) >= 4 and name.lower() in lowered:
        return "Password must not contain your name"
    return None


def require_valid_password(password: str, *, email: str = "", name: str = "") -> None:
    problem = password_problem(password, email=email, name=name)
    if problem:
        raise HTTPException(status_code=400, detail=problem)


# ------------------------------------------------------------------- compare

def constant_time_equals(a: str, b: str) -> bool:
    """Compare secrets without leaking their contents through timing."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())
