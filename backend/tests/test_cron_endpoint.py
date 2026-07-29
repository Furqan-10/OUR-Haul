"""The reminder-trigger endpoint.

On a host that stops an idle instance the in-process scheduler never reaches
07:00, so no compliance reminder is ever sent -- silently, since nothing is
awake to log it. An external cron calls this endpoint instead, which also wakes
the instance.

That makes it a publicly reachable route that sends email to every customer, so
most of what matters here is it refusing to run.
"""
import os

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
URL = f"{BASE}/api/tasks/run-reminders"
SECRET = os.environ.get("CRON_SECRET", "")

# 503 is the correct answer when the deployment has not configured a secret, so
# both it and 401 count as "refused" for the rejection tests.
REFUSED = (401, 503)


class TestAuthorisation:
    def test_no_authorization_header_is_rejected(self):
        response = requests.post(URL, timeout=30)
        assert response.status_code in REFUSED, response.text

    def test_a_wrong_secret_is_rejected(self):
        response = requests.post(
            URL, headers={"Authorization": "Bearer not-the-secret"}, timeout=30)
        assert response.status_code in REFUSED, response.text

    def test_the_bearer_prefix_is_required(self):
        # Guards against a lenient parse that accepts the raw secret, which
        # would also accept it from places that strip the scheme.
        response = requests.post(
            URL, headers={"Authorization": SECRET or "x"}, timeout=30)
        assert response.status_code in REFUSED, response.text

    def test_the_secret_is_not_accepted_as_a_query_parameter(self):
        # Query strings land in access logs, proxies and browser history.
        response = requests.post(f"{URL}?secret={SECRET or 'x'}", timeout=30)
        assert response.status_code in REFUSED, response.text


class TestTriggering:
    def _auth(self):
        if not SECRET:
            pytest.skip("Set CRON_SECRET to exercise a successful trigger")
        return {"Authorization": f"Bearer {SECRET}"}

    def test_an_unknown_job_name_is_rejected(self):
        response = requests.post(f"{URL}?job=hourly", headers=self._auth(), timeout=60)
        assert response.status_code == 400, response.text

    def test_a_valid_call_reports_what_it_ran(self):
        response = requests.post(f"{URL}?job=daily", headers=self._auth(), timeout=120)
        assert response.status_code == 200, response.text
        assert "daily" in response.json()["ran"]

    def test_a_second_immediate_call_is_skipped_by_the_lock(self):
        """The Mongo job lock is what stops two triggers double-sending.

        A null result means the lock was held and this call sent nothing, which
        is different from running and finding nothing to send.
        """
        headers = self._auth()
        requests.post(f"{URL}?job=daily", headers=headers, timeout=120)
        second = requests.post(f"{URL}?job=daily", headers=headers, timeout=120)
        assert second.status_code == 200, second.text
        assert second.json()["ran"]["daily"] is None

    def test_a_bare_call_runs_the_daily_job(self):
        response = requests.post(URL, headers=self._auth(), timeout=120)
        assert response.status_code == 200, response.text
        assert "daily" in response.json()["ran"]
