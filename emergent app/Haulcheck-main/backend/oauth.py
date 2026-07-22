"""Standard Google OAuth 2.0, replacing the Emergent-hosted exchange.

Google sign-in went through `demobackend.emergentagent.com`, which means the
identity of every user of this application was mediated by a third party's demo
environment. That is fine on the platform it was generated on and unacceptable
for a deployment on someone else's account: they cannot see it, rotate it, or
revoke it, and if it disappears their users cannot log in.

This implements the authorization-code flow directly against Google, using the
deploying organisation's own OAuth client. It activates when GOOGLE_CLIENT_ID
and GOOGLE_CLIENT_SECRET are set; without them `is_configured()` is False and
the application falls back to the Emergent path, so nothing breaks for an
existing deployment that has not migrated yet.

## Security notes

**CSRF.** The `state` parameter is generated server-side, stored, and consumed
exactly once. Without it an attacker can feed a victim a callback URL carrying
the attacker's authorization code and silently link the attacker's Google
account to the victim's session.

**Unverified Google emails.** A sign-in whose `email_verified` claim is false is
rejected. Some Google Workspace configurations can hold an address the user has
not proven they own; accepting one would let an attacker register that address
with Google and take over an existing HaulCheck account by email match.

**ID token signature.** The token is read from Google's token endpoint over TLS,
in a server-to-server request authenticated with the client secret, so the
channel itself establishes authenticity -- Google's documentation explicitly
allows skipping signature verification for tokens received this way. The claims
that constrain *who the token is for* (`aud`, `iss`, `exp`) are still checked,
because those are what stop a token minted for a different application being
replayed at this one.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# How long an in-flight sign-in may take between /start and /callback.
STATE_TTL_SECONDS = 600


class OAuthError(Exception):
    """Sign-in could not be completed. The message is safe to show a user."""


def client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def is_configured() -> bool:
    """True when this deployment has its own Google OAuth client."""
    return bool(client_id() and client_secret())


async def ensure_indexes(db) -> None:
    """TTL index so abandoned sign-ins expire instead of accumulating."""
    await db.oauth_states.create_index("state", unique=True)
    await db.oauth_states.create_index("expires_at", expireAfterSeconds=0)


async def begin(db, redirect_uri: str) -> str:
    """Create a one-time state and return the URL to send the browser to."""
    if not is_configured():
        raise OAuthError("Google sign-in is not configured on this server.")

    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({
        "state": state,
        "redirect_uri": redirect_uri,
        # Stored as a real datetime: MongoDB's TTL monitor compares against BSON
        # dates, and an ISO string would simply never be collected.
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
        "created_at": datetime.now(timezone.utc),
    })
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        # `select_account` stops a shared browser silently reusing whichever
        # Google account happens to be signed in.
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def _consume_state(db, state: str) -> dict:
    """Atomically take the state, so a replayed callback cannot reuse it."""
    doc = await db.oauth_states.find_one_and_delete({"state": state})
    if not doc:
        raise OAuthError("This sign-in link has already been used or has expired.")
    expires = doc.get("expires_at")
    if expires and expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise OAuthError("This sign-in link has expired. Please try again.")
    return doc


def _verify_claims(id_token: str) -> dict:
    """Decode the ID token and check the claims that bind it to this client."""
    try:
        claims = jwt.decode(
            id_token,
            algorithms=["RS256"],
            audience=client_id(),
            options={
                # Signature verification is skipped deliberately -- see the
                # module docstring for why the TLS channel establishes
                # authenticity instead.
                "verify_signature": False,
                # PyJWT turns *every* other check off along with the signature,
                # so passing `audience=` above has no effect unless these are
                # re-enabled explicitly. Without them a token minted for a
                # different Google application, or one that expired long ago,
                # would be accepted. Both are covered by tests.
                "verify_aud": True,
                "verify_exp": True,
                "require": ["aud", "exp", "iss", "sub"],
            },
        )
    except jwt.InvalidAudienceError:
        raise OAuthError("This sign-in was issued for a different application.")
    except jwt.ExpiredSignatureError:
        raise OAuthError("This sign-in has expired. Please try again.")
    except jwt.PyJWTError as e:
        logging.warning(f"Google ID token could not be decoded: {e}")
        raise OAuthError("Google sign-in could not be verified.")

    if claims.get("iss") not in VALID_ISSUERS:
        raise OAuthError("Google sign-in could not be verified.")

    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise OAuthError("Google did not return an email address for this account.")

    # See module docstring: an unverified address is an account-takeover vector,
    # because HaulCheck links Google identities to existing accounts by email.
    if not claims.get("email_verified"):
        raise OAuthError(
            "This Google account's email address is not verified. "
            "Verify it with Google, or sign in with a password instead.")

    return {
        "email": email,
        "name": claims.get("name") or "",
        "picture": claims.get("picture"),
        "google_sub": claims.get("sub"),
    }


async def complete(db, code: str, state: str) -> dict:
    """Exchange an authorization code for the verified Google profile.

    Returns `{email, name, picture, google_sub}`. Raises `OAuthError` with a
    message safe to show the user.
    """
    if not is_configured():
        raise OAuthError("Google sign-in is not configured on this server.")

    stored = await _consume_state(db, state)
    redirect_uri = stored.get("redirect_uri")

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            resp = await http.post(TOKEN_ENDPOINT, data={
                "code": code,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
        except httpx.HTTPError as e:
            logging.error(f"Google token exchange failed to connect: {e}")
            raise OAuthError("Could not reach Google to complete sign-in.")

    if resp.status_code != 200:
        # Google's error body names the misconfiguration (redirect_uri_mismatch,
        # invalid_client). Log it -- it is the single most useful thing when
        # setting up a new OAuth client -- but do not return it to the browser.
        logging.error(f"Google token exchange rejected ({resp.status_code}): {resp.text}")
        raise OAuthError("Google rejected this sign-in. Please try again.")

    id_token = resp.json().get("id_token")
    if not id_token:
        raise OAuthError("Google did not return an identity token.")
    return _verify_claims(id_token)
