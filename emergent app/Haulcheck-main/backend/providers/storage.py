"""Object storage for uploaded evidence: photos, signed sheets, certificates.

Two changes from the original inline implementation:

* **It is async.** The previous code called the `requests` library -- which
  blocks -- from inside `async def` handlers. Every upload and download stalled
  the entire event loop for the duration of the round trip, so one slow
  attachment fetch delayed every other request the process was serving. These
  use `httpx.AsyncClient`.

* **It is swappable.** `EmergentStorage` reproduces the existing behaviour
  exactly and stays the default. `S3Storage` is the migration path off the
  platform. `NullStorage` lets the app run and the suite pass with no keys.
"""
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import httpx

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "heic": "image/heic",
}


class StorageUnavailable(RuntimeError):
    """Raised when the configured backend cannot serve a request."""


class StorageProvider(ABC):
    name = "abstract"

    @abstractmethod
    async def put(self, path: str, data: bytes, content_type: str) -> dict:
        """Store bytes and return provider metadata (must include 'path')."""

    @abstractmethod
    async def get(self, path: str) -> Tuple[bytes, str]:
        """Return (bytes, content_type)."""

    async def delete(self, path: str) -> None:
        """Remove an object. Optional -- the app soft-deletes file records."""
        raise NotImplementedError

    async def healthy(self) -> bool:
        return True


class EmergentStorage(StorageProvider):
    """The Emergent platform object store (current default)."""

    name = "emergent"
    BASE = "https://integrations.emergentagent.com/objstore/api/v1/storage"

    def __init__(self, key: str, app_name: str = "haulcheck"):
        self._emergent_key = key
        self._app_name = app_name
        self._storage_key: Optional[str] = None

    async def _auth(self) -> str:
        """Exchange the platform key for a storage key, once."""
        if self._storage_key:
            return self._storage_key
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{self.BASE}/init", json={"emergent_key": self._emergent_key})
            r.raise_for_status()
            self._storage_key = r.json()["storage_key"]
        return self._storage_key

    async def put(self, path: str, data: bytes, content_type: str) -> dict:
        key = await self._auth()
        async with httpx.AsyncClient(timeout=120) as http:
            r = await http.put(f"{self.BASE}/objects/{path}",
                               headers={"X-Storage-Key": key, "Content-Type": content_type},
                               content=data)
            r.raise_for_status()
            return r.json()

    async def get(self, path: str) -> Tuple[bytes, str]:
        key = await self._auth()
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.get(f"{self.BASE}/objects/{path}", headers={"X-Storage-Key": key})
            r.raise_for_status()
            return r.content, r.headers.get("Content-Type", "application/octet-stream")

    async def healthy(self) -> bool:
        try:
            await self._auth()
            return True
        except Exception:
            return False


class S3Storage(StorageProvider):
    """S3-compatible storage (AWS, Cloudflare R2, MinIO, Backblaze B2).

    The migration target. Implemented against the S3 REST API through httpx
    rather than boto3, which is synchronous and would reintroduce the blocking
    problem this module exists to fix.

    Not yet wired to a live bucket -- set STORAGE_PROVIDER=s3 plus the S3_*
    variables to use it, and verify against a scratch bucket before moving
    real evidence.
    """

    name = "s3"

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str,
                 region: str = "auto"):
        self.bucket, self.endpoint = bucket, endpoint.rstrip("/")
        self.access_key, self.secret_key, self.region = access_key, secret_key, region

    def _sign(self, *args, **kwargs):  # pragma: no cover - not yet exercised
        raise NotImplementedError(
            "S3 request signing is not implemented yet. Provide credentials and "
            "complete this method before switching STORAGE_PROVIDER to s3."
        )

    async def put(self, path: str, data: bytes, content_type: str) -> dict:
        raise NotImplementedError(self._unimplemented())

    async def get(self, path: str) -> Tuple[bytes, str]:
        raise NotImplementedError(self._unimplemented())

    @staticmethod
    def _unimplemented() -> str:
        return ("S3Storage is a migration stub. Implement request signing, or keep "
                "STORAGE_PROVIDER=emergent.")


class NullStorage(StorageProvider):
    """No storage configured.

    Fails uploads with a clear message instead of an opaque 502 from a service
    that was never reachable. Used automatically when no key is present, which
    is the normal state in local development.
    """

    name = "null"

    async def put(self, path: str, data: bytes, content_type: str) -> dict:
        raise StorageUnavailable(
            "File storage is not configured. Set EMERGENT_LLM_KEY (or configure "
            "STORAGE_PROVIDER) to enable uploads."
        )

    async def get(self, path: str) -> Tuple[bytes, str]:
        raise StorageUnavailable("File storage is not configured.")

    async def healthy(self) -> bool:
        return False


_provider: Optional[StorageProvider] = None


def get_provider() -> StorageProvider:
    """The configured storage backend, built once."""
    global _provider
    if _provider is not None:
        return _provider

    choice = (os.environ.get("STORAGE_PROVIDER") or "").strip().lower()
    emergent_key = os.environ.get("EMERGENT_LLM_KEY", "").strip()

    if choice == "s3":
        _provider = S3Storage(
            bucket=os.environ["S3_BUCKET"], endpoint=os.environ["S3_ENDPOINT"],
            access_key=os.environ["S3_ACCESS_KEY"], secret_key=os.environ["S3_SECRET_KEY"],
            region=os.environ.get("S3_REGION", "auto"))
    elif choice == "null" or (not choice and not emergent_key):
        # No key locally is the normal case, not an error worth crashing over.
        _provider = NullStorage()
        logging.info("Storage provider: null (no EMERGENT_LLM_KEY configured)")
    else:
        _provider = EmergentStorage(emergent_key)

    logging.info(f"Storage provider: {_provider.name}")
    return _provider


def reset_provider() -> None:
    """Drop the cached provider. For tests that change the environment."""
    global _provider
    _provider = None
