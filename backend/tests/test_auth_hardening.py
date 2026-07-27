"""Phase 2 authentication hardening.

Covers the controls added for public signup: password policy, login and
driver-login rate limiting, and token revocation. Some tests deliberately trip
a lockout, so each uses a fresh identifier to avoid locking out the shared seed
account for the rest of the run.
"""
import uuid

import pytest
import requests

from conftest import _resolve_base_url

API = f"{_resolve_base_url()}/api"
GOOD_PASSWORD = "Reliable-Fleet-2026!"
TIMEOUT = 20


def _email():
    return f"test_sec_{uuid.uuid4().hex[:10]}@haulcheck-test.co.uk"


def _own_ip() -> dict:
    """A unique X-Forwarded-For per caller.

    Every test here shares the loopback address, so a test that deliberately
    trips the per-IP limit would lock out its neighbours. Giving each its own
    forwarded address isolates the rate-limit buckets. The test backend runs
    with TRUST_PROXY_HEADERS=1 so this header is honoured; in production the
    header is ignored unless a real proxy is configured (see security.client_ip).
    """
    octet = lambda: __import__("random").randint(1, 254)
    return {"X-Forwarded-For": f"{octet()}.{octet()}.{octet()}.{octet()}"}


class TestPasswordPolicy:
    @pytest.mark.parametrize("password", [
        "short",             # under 12
        "Test1234!",         # the old 9-char seed password
        "password1234",      # contains a blocklisted word
        "aaaaaaaaaaaaaa",    # too few distinct characters
        "abcdefghijklmno",   # sequential run
    ])
    def test_weak_password_rejected_at_registration(self, password):
        r = requests.post(f"{API}/auth/register",
                          json={"email": _email(), "password": password, "name": "Weak"},
                          timeout=TIMEOUT)
        assert r.status_code == 400, f"{password!r} should have been rejected: {r.text}"

    def test_strong_password_accepted(self):
        r = requests.post(f"{API}/auth/register",
                          json={"email": _email(), "password": GOOD_PASSWORD, "name": "Strong"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_password_may_not_contain_the_email(self):
        # The whole local part must appear in the password to trip the rule,
        # so build the password from the exact local part used to register.
        local = f"transporterjoe{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/auth/register",
                          json={"email": f"{local}@haulcheck-test.co.uk",
                                "password": f"{local}Zz9!", "name": "Joe"},
                          timeout=TIMEOUT)
        assert r.status_code == 400


class TestLoginRateLimiting:
    def test_repeated_failures_eventually_lock_out(self):
        """A single account cannot be guessed at indefinitely."""
        ip = _own_ip()
        email = _email()
        requests.post(f"{API}/auth/register",
                      json={"email": email, "password": GOOD_PASSWORD, "name": "Target"},
                      headers=ip, timeout=TIMEOUT)
        saw_lockout = False
        for _ in range(15):
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "wrong-guess-here"},
                              headers=ip, timeout=TIMEOUT)
            if r.status_code == 429:
                saw_lockout = True
                break
            assert r.status_code == 401
        assert saw_lockout, "brute-force login was never rate-limited"

    def test_lockout_blocks_even_the_correct_password(self):
        """Once locked, the real password is refused too -- the limit is on
        attempts, not on wrong answers."""
        ip = _own_ip()
        email = _email()
        requests.post(f"{API}/auth/register",
                      json={"email": email, "password": GOOD_PASSWORD, "name": "Locked"},
                      headers=ip, timeout=TIMEOUT)
        for _ in range(12):
            requests.post(f"{API}/auth/login",
                          json={"email": email, "password": "nope"}, headers=ip, timeout=TIMEOUT)
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": GOOD_PASSWORD}, headers=ip, timeout=TIMEOUT)
        assert r.status_code == 429


class TestDriverLoginRateLimiting:
    def test_access_code_guessing_is_rate_limited(self):
        """The globally-matched driver code cannot be swept.

        Each guess is a different code, so per-code limiting never fires -- only
        the per-IP limit stops a sweep. Uses one dedicated address for the loop.
        """
        ip = _own_ip()
        saw_lockout = False
        for _ in range(45):
            r = requests.post(f"{API}/driver/login",
                              json={"code": uuid.uuid4().hex[:6].upper()},
                              headers=ip, timeout=TIMEOUT)
            if r.status_code == 429:
                saw_lockout = True
                break
            assert r.status_code == 401
        assert saw_lockout, "driver access-code guessing was never rate-limited"


class TestSharedAddressIsNotPunished:
    """A whole office behind one IP must not be locked out by its neighbours.

    Organisations sit behind a single NAT gateway. An early version limited
    logins per IP as tightly as per account, so unrelated users sharing an
    address accumulated into one bucket -- a handful of mistyped passwords
    across the office locked everyone out. It also broke this very test suite,
    where every request comes from the loopback address.

    The per-identifier limit stays tight; the per-address limit is loose.
    """

    def test_many_accounts_from_one_address_still_work(self):
        ip = _own_ip()          # one shared "office" address
        accounts = []
        for _ in range(4):
            email = _email()
            requests.post(f"{API}/auth/register",
                          json={"email": email, "password": GOOD_PASSWORD, "name": "Staff"},
                          headers=ip, timeout=TIMEOUT)
            accounts.append(email)

        # Each colleague mistypes their password a few times...
        for email in accounts:
            for _ in range(3):
                requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "mistyped-again"},
                              headers=ip, timeout=TIMEOUT)

        # ...and everyone can still sign in with the right password.
        for email in accounts:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": GOOD_PASSWORD},
                              headers=ip, timeout=TIMEOUT)
            assert r.status_code == 200, \
                f"a shared address was locked out by unrelated users: {r.status_code} {r.text}"


class TestDriverTokenRevocation:
    """Rotating a driver's access code must retire tokens issued against it.

    This is the fix for a lost handset: a 30-day driver token was
    unrevocable, so a lost phone meant up to a month of access. Rotating the
    code now invalidates the old token immediately.
    """

    def _manager(self, ip):
        email = _email()
        r = requests.post(f"{API}/auth/register",
                          json={"email": email, "password": GOOD_PASSWORD, "name": "TM"},
                          headers=ip, timeout=TIMEOUT)
        return {"Authorization": f"Bearer {r.json()['token']}", **ip}

    def test_rotating_the_code_invalidates_the_old_token(self):
        ip = _own_ip()
        headers = self._manager(ip)
        drv = requests.post(f"{API}/drivers", headers=headers,
                            json={"name": "TEST Driver"}, timeout=TIMEOUT).json()
        code = requests.post(f"{API}/drivers/{drv['id']}/access-code",
                             headers=headers, timeout=TIMEOUT).json()["access_code"]

        login = requests.post(f"{API}/driver/login", json={"code": code}, headers=ip, timeout=TIMEOUT)
        assert login.status_code == 200, login.text
        driver_headers = {"Authorization": f"Bearer {login.json()['token']}"}
        assert requests.get(f"{API}/driver/me", headers=driver_headers,
                            timeout=TIMEOUT).status_code == 200

        # Re-issue the code; the previously held token must now be refused.
        requests.post(f"{API}/drivers/{drv['id']}/access-code", headers=headers, timeout=TIMEOUT)
        assert requests.get(f"{API}/driver/me", headers=driver_headers, timeout=TIMEOUT).status_code == 401

    def test_revoking_the_code_blocks_login_and_token(self):
        ip = _own_ip()
        headers = self._manager(ip)
        drv = requests.post(f"{API}/drivers", headers=headers,
                            json={"name": "TEST Driver 2"}, timeout=TIMEOUT).json()
        code = requests.post(f"{API}/drivers/{drv['id']}/access-code",
                             headers=headers, timeout=TIMEOUT).json()["access_code"]
        token = requests.post(f"{API}/driver/login", json={"code": code},
                              headers=ip, timeout=TIMEOUT).json()["token"]

        requests.delete(f"{API}/drivers/{drv['id']}/access-code", headers=headers, timeout=TIMEOUT)
        # The held token is dead...
        assert requests.get(f"{API}/driver/me",
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=TIMEOUT).status_code == 401
        # ...and the revoked code can no longer be used to obtain a new one.
        assert requests.post(f"{API}/driver/login", json={"code": code},
                             headers=ip, timeout=TIMEOUT).status_code == 401


class TestEmailVerification:
    def test_new_account_starts_unverified(self):
        r = requests.post(f"{API}/auth/register",
                          json={"email": _email(), "password": GOOD_PASSWORD, "name": "Unv"},
                          timeout=TIMEOUT)
        token = r.json()["token"]
        me = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT).json()
        assert me.get("email_verified") is False

    def test_resend_verification_is_accepted(self):
        r = requests.post(f"{API}/auth/register",
                          json={"email": _email(), "password": GOOD_PASSWORD, "name": "Unv"},
                          timeout=TIMEOUT)
        headers = {"Authorization": f"Bearer {r.json()['token']}"}
        # Email delivery is best-effort (no key locally); the endpoint must still
        # succeed rather than error.
        assert requests.post(f"{API}/auth/resend-verification", headers=headers,
                             timeout=TIMEOUT).status_code == 200

    def test_invalid_verification_token_rejected(self):
        r = requests.post(f"{API}/auth/verify-email", json={"token": "not-a-real-token"},
                          timeout=TIMEOUT)
        assert r.status_code == 400


class TestFileDownloadAuth:
    def test_query_param_token_is_no_longer_accepted(self):
        """A token in ?auth= must not authenticate a file download.

        Credentials in URLs leak into logs, history and Referer headers; the
        parameter was removed.
        """
        reg = _email()
        r = requests.post(f"{API}/auth/register",
                          json={"email": reg, "password": GOOD_PASSWORD, "name": "Files"},
                          timeout=TIMEOUT)
        token = r.json()["token"]
        # A made-up file id is fine: we assert on the auth outcome, not the file.
        r = requests.get(f"{API}/files/nonexistent?auth={token}", timeout=TIMEOUT)
        assert r.status_code == 401, \
            "the ?auth= query parameter must no longer authenticate a request"
