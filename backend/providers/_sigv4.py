"""AWS Signature Version 4, for the S3 REST API.

boto3 implements this already, and is deliberately not used: it is synchronous,
and one blocking call inside an `async def` handler stalls every other request
the process is serving. That is the problem `storage.py` was rewritten around,
so pulling boto3 back in to avoid writing this would undo it.

Signing is a pure function of the request, which makes it cheap to implement and
exhaustively testable without a network. `tests/test_sigv4.py` checks the output
against botocore rather than against pasted digests -- a signature that is merely
plausible produces `SignatureDoesNotMatch` and no uploads at all, and a constant
mistyped consistently in two places would hide exactly that.

Reference: https://docs.aws.amazon.com/IAM/latest/UserGuide/create-signed-request.html
"""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"

# SHA-256 of zero bytes. Required as `x-amz-content-sha256` on bodyless
# requests; S3 rejects the request outright without that header.
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Derive the request-scoped signing key.

    Scoped by date, region and service so a captured signature cannot be
    replayed against another day, region or service.
    """
    k_date = _hmac(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def _canonical_uri(path: str) -> str:
    """Percent-encode the path, keeping `/` as the separator.

    S3 does *not* double-encode the path, unlike most other AWS services. `~` is
    unreserved and must be left alone -- encoding it is a silent mismatch that
    only affects the keys that happen to contain one.
    """
    return quote(path, safe="/~") or "/"


def _canonical_query(query: str) -> str:
    """Sort and encode query parameters, as the canonical request requires."""
    if not query:
        return ""
    pairs = []
    for part in query.split("&"):
        name, _, value = part.partition("=")
        pairs.append((quote(name, safe="~"), quote(value, safe="~")))
    pairs.sort()
    return "&".join(f"{name}={value}" for name, value in pairs)


def sign(*, method: str, url: str, headers: Dict[str, str], payload: bytes,
         access_key: str, secret_key: str, region: str, service: str = "s3",
         now: Optional[datetime] = None) -> Dict[str, str]:
    """Return a new header dict carrying the SigV4 `Authorization` header.

    The caller's `headers` are copied, never mutated: callers reuse their header
    dict across retries, and a second signing pass over already-signed headers
    produces a signature the server rejects.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parts = urlsplit(url)
    payload_hash = sha256_hex(payload)

    signed: Dict[str, str] = dict(headers)
    signed["host"] = parts.netloc
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_hash

    # Canonical headers are lowercase, whitespace-collapsed and name-sorted.
    canonical_pairs = sorted(
        (name.lower(), " ".join(str(value).split())) for name, value in signed.items())
    canonical_headers = "".join(f"{name}:{value}\n" for name, value in canonical_pairs)
    signed_header_names = ";".join(name for name, _ in canonical_pairs)

    canonical_request = "\n".join([
        method.upper(),
        _canonical_uri(parts.path),
        _canonical_query(parts.query),
        canonical_headers,
        signed_header_names,
        payload_hash,
    ])

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        ALGORITHM, amz_date, scope, sha256_hex(canonical_request.encode("utf-8"))])

    signature = hmac.new(
        signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    signed["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_header_names}, Signature={signature}")
    return signed
