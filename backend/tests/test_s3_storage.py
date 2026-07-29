"""S3Storage against an S3-compatible endpoint (Cloudflare R2).

The round-trip tests need a real bucket, so they skip unless the S3_* variables
are set. Everything else runs anywhere: URL construction and error translation,
which is where the bugs that reach production live. A signing error is loud --
the server says SignatureDoesNotMatch. A path built wrong is silent until
somebody cannot find their evidence.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import storage as storage_module  # noqa: E402

LIVE = all(os.environ.get(k) for k in
           ("S3_BUCKET", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"))
requires_bucket = pytest.mark.skipif(
    not LIVE, reason="Set S3_BUCKET/S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY to run")


def _provider():
    return storage_module.S3Storage(
        bucket="haulcheck", endpoint="https://acct123.r2.cloudflarestorage.com",
        access_key="AKIDEXAMPLE", secret_key="secret", region="auto")


class TestUrlConstruction:
    """R2 uses path-style addressing: <endpoint>/<bucket>/<key>."""

    def test_key_is_appended_to_bucket(self):
        assert _provider()._url("defects/photo.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/defects/photo.jpg")

    def test_a_leading_slash_on_the_key_does_not_double_up(self):
        assert _provider()._url("/defects/photo.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/defects/photo.jpg")

    def test_a_trailing_slash_on_the_endpoint_does_not_double_up(self):
        provider = storage_module.S3Storage(
            bucket="haulcheck", endpoint="https://acct123.r2.cloudflarestorage.com/",
            access_key="k", secret_key="s")
        assert provider._url("a.jpg") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/a.jpg")

    def test_empty_key_addresses_the_bucket_itself(self):
        # What the health check probes.
        assert _provider()._url("") == (
            "https://acct123.r2.cloudflarestorage.com/haulcheck/")


class TestConfiguration:
    def test_region_defaults_to_auto(self):
        provider = storage_module.S3Storage(
            bucket="b", endpoint="https://e", access_key="k", secret_key="s")
        assert provider.region == "auto"

    def test_an_empty_region_becomes_auto(self):
        # R2 accepts only "auto"; an empty value signs a scope the server
        # rejects with an error that never mentions the region.
        provider = storage_module.S3Storage(
            bucket="b", endpoint="https://e", access_key="k", secret_key="s", region="")
        assert provider.region == "auto"

    def test_the_migration_stub_is_gone(self):
        assert not hasattr(storage_module.S3Storage, "_unimplemented"), (
            "S3Storage._unimplemented is a leftover from the stub")
        assert not hasattr(storage_module.S3Storage, "_sign"), (
            "S3Storage._sign is a leftover from the stub; signing lives in _sigv4")

    def test_it_satisfies_the_provider_interface(self):
        for name in ("put", "get", "delete", "healthy"):
            assert callable(getattr(storage_module.S3Storage, name, None)), name


class TestProviderSelection:
    def test_s3_is_selected_by_env(self, monkeypatch):
        for k, v in {"STORAGE_PROVIDER": "s3", "S3_BUCKET": "b",
                     "S3_ENDPOINT": "https://e", "S3_ACCESS_KEY": "k",
                     "S3_SECRET_KEY": "s", "S3_REGION": "auto"}.items():
            monkeypatch.setenv(k, v)
        storage_module.reset_provider()
        try:
            assert storage_module.get_provider().name == "s3"
        finally:
            storage_module.reset_provider()

    def test_no_configuration_selects_null_rather_than_crashing(self, monkeypatch):
        # A client deploying on their own account has no keys on day one.
        for k in ("STORAGE_PROVIDER", "EMERGENT_LLM_KEY"):
            monkeypatch.delenv(k, raising=False)
        storage_module.reset_provider()
        try:
            assert storage_module.get_provider().name == "null"
        finally:
            storage_module.reset_provider()


@requires_bucket
class TestRoundTripAgainstARealBucket:
    @pytest.mark.asyncio
    async def test_put_then_get_returns_the_same_bytes(self):
        provider = storage_module.get_provider()
        key = f"tests/{uuid.uuid4().hex}.txt"
        payload = b"walkaround-sheet-bytes"
        meta = await provider.put(key, payload, "text/plain")
        assert meta["path"] == key
        data, content_type = await provider.get(key)
        assert data == payload
        assert content_type.startswith("text/plain")
        await provider.delete(key)

    @pytest.mark.asyncio
    async def test_a_key_with_spaces_and_brackets_round_trips(self):
        # Uploaded filenames reach the key unmodified.
        provider = storage_module.get_provider()
        key = f"tests/sheet (1) {uuid.uuid4().hex[:6]}.pdf"
        await provider.put(key, b"%PDF-1.4 fake", "application/pdf")
        data, _ = await provider.get(key)
        assert data == b"%PDF-1.4 fake"
        await provider.delete(key)

    @pytest.mark.asyncio
    async def test_get_after_delete_reports_it_is_missing(self):
        provider = storage_module.get_provider()
        key = f"tests/{uuid.uuid4().hex}.txt"
        await provider.put(key, b"x", "text/plain")
        await provider.delete(key)
        with pytest.raises(storage_module.StorageUnavailable):
            await provider.get(key)

    @pytest.mark.asyncio
    async def test_healthy_is_true_for_a_reachable_bucket(self):
        assert await storage_module.get_provider().healthy() is True
