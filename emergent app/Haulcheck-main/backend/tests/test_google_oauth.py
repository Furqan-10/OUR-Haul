"""Standard Google OAuth: state handling, claim validation, and config gating.

None of this needs real Google credentials -- which is the point. The parts
worth testing are the ones that decide *whether to trust a sign-in*, and those
are all local: is the state fresh and unused, is the token addressed to this
client, has Google actually verified the address.

The token exchange itself is one HTTPS POST and is not mocked here; a test that
asserts httpx was called with certain arguments would only restate the
implementation.
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
import oauth  # noqa: E402

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000")
API = f"{BASE}/api"

CLIENT_ID = "test-client-id.apps.googleusercontent.com"


def _db():
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
    if not os.environ.get("MONGO_URL"):
        pytest.skip("MONGO_URL not configured")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture
def configured(monkeypatch):
    """Pretend this deployment has its own Google OAuth client."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    return CLIENT_ID


def _id_token(**overrides):
    """Build an ID token shaped like Google's."""
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "driver@haulage.example",
        "email_verified": True,
        "name": "Test Operator",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return jwt.encode(claims, "irrelevant-signing-key", algorithm="HS256")


class TestClaimVerification:
    def test_a_valid_token_yields_the_profile(self, configured):
        profile = oauth._verify_claims(_id_token())
        assert profile["email"] == "driver@haulage.example"
        assert profile["google_sub"] == "1234567890"

    def test_a_token_for_another_client_is_rejected(self, configured):
        """The core replay defence.

        Without the audience check, an ID token minted for any other Google
        application could be presented here and accepted, letting the holder
        sign in as whoever that token names.
        """
        with pytest.raises(oauth.OAuthError):
            oauth._verify_claims(_id_token(aud="someone-elses-client.apps.googleusercontent.com"))

    def test_an_unverified_google_address_is_rejected(self, configured):
        """Account-takeover defence.

        Accounts are linked to Google identities by email address. If an
        unverified address were accepted, anyone able to put an address on a
        Google account could claim the matching HaulCheck account.
        """
        with pytest.raises(oauth.OAuthError) as excinfo:
            oauth._verify_claims(_id_token(email_verified=False))
        assert "not verified" in str(excinfo.value).lower()

    def test_an_expired_token_is_rejected(self, configured):
        with pytest.raises(oauth.OAuthError):
            oauth._verify_claims(_id_token(exp=int(time.time()) - 60))

    def test_a_token_from_the_wrong_issuer_is_rejected(self, configured):
        with pytest.raises(oauth.OAuthError):
            oauth._verify_claims(_id_token(iss="https://accounts.evil.example"))

    def test_a_token_with_no_email_is_rejected(self, configured):
        with pytest.raises(oauth.OAuthError):
            oauth._verify_claims(_id_token(email=""))

    def test_the_email_is_normalised(self, configured):
        """Registration lower-cases addresses; sign-in must match, or Google
        login would create a second account for the same person."""
        profile = oauth._verify_claims(_id_token(email="  Driver@Haulage.Example  "))
        assert profile["email"] == "driver@haulage.example"


class TestStateIsSingleUse:
    def test_a_state_cannot_be_replayed(self, configured):
        """CSRF defence: consuming the state must be atomic and final."""
        async def run():
            db = _db()
            await oauth.ensure_indexes(db)
            url = await oauth.begin(db, "http://localhost:3000/auth/google/callback")
            state = url.split("state=")[1].split("&")[0]

            first = await oauth._consume_state(db, state)
            assert first["redirect_uri"].endswith("/auth/google/callback")

            with pytest.raises(oauth.OAuthError):
                await oauth._consume_state(db, state)
        asyncio.run(run())

    def test_concurrent_callbacks_consume_a_state_once(self, configured):
        """Two callbacks racing on one state: exactly one may win."""
        async def run():
            db = _db()
            await oauth.ensure_indexes(db)
            url = await oauth.begin(db, "http://localhost:3000/auth/google/callback")
            state = url.split("state=")[1].split("&")[0]

            results = await asyncio.gather(
                *[oauth._consume_state(db, state) for _ in range(5)],
                return_exceptions=True)
            winners = [r for r in results if not isinstance(r, Exception)]
            assert len(winners) == 1, (
                f"{len(winners)} callbacks consumed the same state; exactly one may.")
        asyncio.run(run())

    def test_an_unknown_state_is_rejected(self, configured):
        async def run():
            db = _db()
            with pytest.raises(oauth.OAuthError):
                await oauth._consume_state(db, f"never-issued-{uuid.uuid4().hex}")
        asyncio.run(run())

    def test_an_expired_state_is_rejected(self, configured):
        async def run():
            db = _db()
            state = f"expired-{uuid.uuid4().hex}"
            await db.oauth_states.insert_one({
                "state": state,
                "redirect_uri": "http://localhost:3000/auth/google/callback",
                "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
                "created_at": datetime.now(timezone.utc),
            })
            with pytest.raises(oauth.OAuthError):
                await oauth._consume_state(db, state)
        asyncio.run(run())

    def test_the_authorization_url_carries_the_expected_parameters(self, configured):
        async def run():
            db = _db()
            url = await oauth.begin(db, "http://localhost:3000/auth/google/callback")
            assert url.startswith(oauth.AUTH_ENDPOINT)
            for expected in ("response_type=code", "scope=openid", "state=",
                             "prompt=select_account", f"client_id={CLIENT_ID}"):
                assert expected in url, f"missing {expected} in {url}"
        asyncio.run(run())


class TestConfigGating:
    def test_not_configured_without_both_credentials(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-only")
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        assert oauth.is_configured() is False

    def test_begin_refuses_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

        async def run():
            with pytest.raises(oauth.OAuthError):
                await oauth.begin(_db(), "http://localhost:3000/auth/google/callback")
        asyncio.run(run())


class TestEndpoints:
    """The live API surface. The server under test has no Google client
    configured, so these assert the unconfigured behaviour -- which is exactly
    what a client sees before they set their keys up."""

    def test_config_endpoint_is_public_and_honest(self):
        r = requests.get(f"{API}/auth/google/config", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "enabled" in body and "provider" in body

    def test_start_is_refused_when_unconfigured(self):
        r = requests.post(f"{API}/auth/google/start",
                          json={"redirect_uri": "http://localhost:3000/auth/google/callback"},
                          timeout=10)
        # 400 either because OAuth is unconfigured or the origin is not allowed;
        # both are refusals, and neither is a 500.
        assert r.status_code == 400, r.text

    def test_a_foreign_redirect_uri_is_refused(self):
        """Open-redirect defence: Google must never be told to deliver an
        authorization code to a host this deployment does not serve."""
        r = requests.post(f"{API}/auth/google/start",
                          json={"redirect_uri": "https://attacker.example/steal"},
                          timeout=10)
        assert r.status_code == 400, r.text

    def test_callback_requires_code_and_state(self):
        r = requests.post(f"{API}/auth/google/callback", json={}, timeout=10)
        assert r.status_code == 400

    def test_callback_rejects_an_unknown_state(self):
        r = requests.post(f"{API}/auth/google/callback",
                          json={"code": "abc", "state": f"bogus-{uuid.uuid4().hex}"},
                          timeout=10)
        assert r.status_code == 401
