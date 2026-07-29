"""SigV4 correctness, checked against botocore's reference implementation.

The expected values are computed by botocore at test time rather than pasted in
as constants. A digest typed from memory that happens to be wrong would send
the next person hunting a bug that is not there; a digest typed wrong in *both*
places would pass while the storage backend rejects every request. Comparing
against the implementation AWS ships removes both failure modes.

botocore is a test dependency only. Importing boto3/botocore from application
code is blocked by test_provider_decoupling.py, because it is synchronous and
would stall the event loop from an async handler. Here it never runs in a
request path.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import _sigv4  # noqa: E402

FROZEN = dt.datetime(2026, 7, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
ACCESS = "AKIDEXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
ENDPOINT = "https://acct123.r2.cloudflarestorage.com"


def _ours(method, url, payload, headers=None):
    return _sigv4.sign(
        method=method, url=url, headers=headers or {}, payload=payload,
        access_key=ACCESS, secret_key=SECRET, region="auto", service="s3",
        now=FROZEN)


def _botocore_authorization(method, url, payload, headers=None):
    """The same request signed by botocore, for comparison."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    stamp = FROZEN.strftime("%Y%m%dT%H%M%SZ")
    hdrs = dict(headers or {})
    hdrs["X-Amz-Date"] = stamp
    hdrs["X-Amz-Content-SHA256"] = _sigv4.sha256_hex(payload)

    request = AWSRequest(method=method, url=url, data=payload, headers=hdrs)
    # botocore reads the timestamp from the request context, which is what lets
    # this compare a fixed instant instead of "now".
    request.context["timestamp"] = stamp

    auth = SigV4Auth(Credentials(ACCESS, SECRET), "s3", "auto")
    canonical = auth.canonical_request(request)
    to_sign = auth.string_to_sign(request, canonical)
    signature = auth.signature(to_sign, request)
    signed_headers = auth.signed_headers(auth.headers_to_sign(request))
    # botocore's scope() already begins with the access key, so it is the whole
    # Credential value -- not a suffix to it.
    return (f"AWS4-HMAC-SHA256 Credential={auth.scope(request)}, "
            f"SignedHeaders={signed_headers}, Signature={signature}")


class TestAgreesWithBotocore:
    """If these diverge, R2 answers SignatureDoesNotMatch and nothing uploads."""

    def setup_method(self):
        pytest.importorskip(
            "botocore",
            reason="botocore is a dev dependency: pip install -r requirements-dev.txt")

    def test_put_with_a_body(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        headers = {"Content-Type": "image/jpeg"}
        payload = b"binary-evidence-bytes"
        assert (_ours("PUT", url, payload, headers)["Authorization"]
                == _botocore_authorization("PUT", url, payload, headers))

    def test_get_with_an_empty_body(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        assert (_ours("GET", url, b"")["Authorization"]
                == _botocore_authorization("GET", url, b""))

    def test_key_containing_characters_that_need_encoding(self):
        # Uploaded filenames reach the key unmodified, so spaces and brackets
        # are routine. Encoding them differently from the server is the classic
        # SigV4 bug, and it only shows up for the files that contain them.
        url = f"{ENDPOINT}/haulcheck/walkaround/sheet%20%281%29.pdf"
        assert (_ours("GET", url, b"")["Authorization"]
                == _botocore_authorization("GET", url, b""))

    def test_key_with_a_tilde(self):
        # `~` is unreserved: encoding it is a common and silent mismatch.
        url = f"{ENDPOINT}/haulcheck/defects/photo~1.jpg"
        assert (_ours("GET", url, b"")["Authorization"]
                == _botocore_authorization("GET", url, b""))

    def test_delete(self):
        url = f"{ENDPOINT}/haulcheck/defects/photo.jpg"
        assert (_ours("DELETE", url, b"")["Authorization"]
                == _botocore_authorization("DELETE", url, b""))

    def test_bucket_level_head(self):
        # How the health check probes the bucket.
        url = f"{ENDPOINT}/haulcheck/"
        assert (_ours("HEAD", url, b"")["Authorization"]
                == _botocore_authorization("HEAD", url, b""))


class TestSignedHeaders:
    def test_required_headers_are_added(self):
        signed = _ours("GET", f"{ENDPOINT}/haulcheck/x", b"")
        assert signed["host"] == "acct123.r2.cloudflarestorage.com"
        assert signed["x-amz-date"] == "20260728T120000Z"
        assert signed["x-amz-content-sha256"] == _sigv4.EMPTY_SHA256
        assert signed["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=")

    def test_the_callers_headers_are_not_mutated(self):
        # Callers reuse their header dict across retries.
        original = {"Content-Type": "image/jpeg"}
        _ours("PUT", f"{ENDPOINT}/haulcheck/x", b"data", original)
        assert original == {"Content-Type": "image/jpeg"}

    def test_caller_headers_are_carried_through_and_signed(self):
        signed = _ours("PUT", f"{ENDPOINT}/haulcheck/x", b"d", {"Content-Type": "image/png"})
        assert signed["Content-Type"] == "image/png"
        assert "content-type" in signed["Authorization"].split("SignedHeaders=")[1]

    def test_empty_payload_hash_is_the_sha256_of_no_bytes(self):
        assert _sigv4.EMPTY_SHA256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_signing_key_is_deterministic_and_32_bytes(self):
        a = _sigv4.signing_key(SECRET, "20260728", "auto", "s3")
        b = _sigv4.signing_key(SECRET, "20260728", "auto", "s3")
        assert a == b and len(a) == 32

    def test_signing_key_changes_with_every_scope_component(self):
        base = _sigv4.signing_key(SECRET, "20260728", "auto", "s3")
        assert _sigv4.signing_key(SECRET, "20260729", "auto", "s3") != base
        assert _sigv4.signing_key(SECRET, "20260728", "us-east-1", "s3") != base
        assert _sigv4.signing_key(SECRET, "20260728", "auto", "iam") != base
