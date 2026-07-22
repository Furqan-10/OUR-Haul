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

    def test_start_behaves_according_to_how_the_server_is_configured(self):
        """Asserts against the server's own reported state rather than assuming.

        The suite runs both ways -- against a deployment with Google configured
        and one without -- so hard-coding either outcome makes this test fail
        for the wrong reason.
        """
        configured = requests.get(f"{API}/auth/google/config", timeout=10).json()
        r = requests.post(f"{API}/auth/google/start",
                          json={"redirect_uri": "http://localhost:3000/auth/google/callback"},
                          timeout=10)
        if configured.get("provider") == "google" and configured.get("enabled"):
            assert r.status_code == 200, r.text
            assert r.json()["authorization_url"].startswith(oauth.AUTH_ENDPOINT)
        else:
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


class TestLoginCSRF:
    """The callback must only complete in the browser that began the flow.

    Without this, an attacker completes their own Google authorization inside a
    victim's browser: the victim is silently signed in to the *attacker's*
    account and every record they then enter -- vehicles, drivers, documents --
    lands in an account the attacker controls. A single-use state does not stop
    it, because the attacker spends the state exactly once, in the victim's
    browser.
    """

    def test_a_callback_with_no_cookie_is_refused(self):
        """The victim's browser never called /start, so it holds no cookie."""
        state = f"attacker-supplied-{uuid.uuid4().hex}"
        r = requests.post(f"{API}/auth/google/callback",
                          json={"code": "attacker-code", "state": state},
                          timeout=10)
        assert r.status_code == 401, r.text
        assert "browser" in r.json().get("detail", "").lower()

    def test_a_callback_whose_cookie_disagrees_is_refused(self):
        """A browser mid-flow of its own must not complete someone else's."""
        session = requests.Session()
        session.cookies.set("oauth_state", f"this-browsers-own-{uuid.uuid4().hex}")
        r = session.post(f"{API}/auth/google/callback",
                         json={"code": "attacker-code",
                               "state": f"attackers-{uuid.uuid4().hex}"},
                         timeout=10)
        assert r.status_code == 401, r.text

    def test_the_cookie_check_runs_before_the_state_is_consumed(self, configured):
        """A forged callback must not burn a real in-flight sign-in.

        If the state were consumed first, an attacker who learned a victim's
        state could invalidate it and break their sign-in -- a denial of
        service on top of the CSRF.
        """
        async def run():
            db = _db()
            await oauth.ensure_indexes(db)
            url = await oauth.begin(db, "http://localhost:3000/auth/google/callback")
            state = url.split("state=")[1].split("&")[0]

            # Forged callback: right state, no matching cookie.
            r = requests.post(f"{API}/auth/google/callback",
                              json={"code": "forged", "state": state}, timeout=10)
            assert r.status_code == 401

            # The genuine state must still be there for the real browser.
            still_there = await db.oauth_states.find_one({"state": state})
            assert still_there is not None, (
                "A forged callback consumed a legitimate state, which would "
                "break the real user's sign-in.")
            await db.oauth_states.delete_one({"state": state})
        asyncio.run(run())

    def test_start_sets_an_httponly_state_cookie(self):
        """The cookie must be unreadable to script, or XSS could forge a flow."""
        r = requests.post(f"{API}/auth/google/start",
                          json={"redirect_uri": "http://localhost:3000/auth/google/callback"},
                          timeout=10)
        if r.status_code == 400:
            pytest.skip("Google OAuth is not configured on the server under test")
        cookie = r.headers.get("set-cookie", "")
        assert "oauth_state=" in cookie
        assert "HttpOnly" in cookie
