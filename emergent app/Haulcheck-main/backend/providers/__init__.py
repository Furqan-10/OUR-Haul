"""Pluggable external services.

Object storage, AI and email were called directly by name from route code, with
Emergent's endpoints and key hard-wired in. That made the platform's most
critical paths -- uploading evidence, drafting letters, sending defect alerts --
dependent on services we neither control nor can substitute.

Each module here defines a small interface, an Emergent/Resend implementation
that preserves today's exact behaviour, an alternative or stub for migrating
off, and a null implementation so tests and local development work without any
keys at all.

Selection is by environment variable; the default keeps the current providers,
so nothing changes until it is deliberately switched.
"""
from . import ai, email, storage  # noqa: F401

__all__ = ["ai", "email", "storage"]
