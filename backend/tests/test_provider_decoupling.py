"""Static guard: vendors are named inside `providers/`, nowhere else.

The point of the provider layer is that the application can run on whoever's
account it is deployed to. An inline `from emergentintegrations...` or a bare
`resend.api_key = ...` in a route re-couples the app to one vendor, and it does
so *invisibly* -- the code still works on the machine of whoever wrote it,
because their key happens to be in the environment. It breaks for the next
person, at runtime, in a feature they may not test.

Like `test_tenancy_guard.py`, this reads source rather than behaviour: needing a
real Emergent/Resend/Anthropic key to detect the coupling would mean never
detecting it in CI.
"""
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
PROVIDERS = BACKEND / "providers"

sys.path.insert(0, str(BACKEND))

# Modules that may legitimately name a vendor SDK: the provider package itself
# is where the vendor lives, by design.
ALLOWED = {PROVIDERS / "ai.py", PROVIDERS / "email.py", PROVIDERS / "storage.py"}

# Vendor SDK imports and the module-level credential assignment each one uses.
VENDOR_PATTERNS = {
    "emergentintegrations": re.compile(r"\bimport\s+emergentintegrations|\bfrom\s+emergentintegrations"),
    "resend": re.compile(r"\bimport\s+resend\b|\bfrom\s+resend\b"),
    "anthropic": re.compile(r"\bimport\s+anthropic\b|\bfrom\s+anthropic\b"),
    "boto3": re.compile(r"\bimport\s+boto3\b|\bfrom\s+boto3\b"),
}


def _python_files():
    for path in BACKEND.glob("*.py"):
        yield path
    for path in PROVIDERS.glob("*.py"):
        yield path


def test_no_vendor_sdk_imported_outside_the_provider_package():
    violations = []
    for path in _python_files():
        if path in ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        for vendor, pattern in VENDOR_PATTERNS.items():
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                violations.append(f"  {path.name}:{line}  imports `{vendor}`")

    assert not violations, (
        "Vendor SDKs must only be imported inside backend/providers/.\n\n"
        "Naming a vendor in application code means the feature only works for a\n"
        "deployment holding that vendor's credentials -- and it fails at runtime,\n"
        "not at startup, so it looks fine until a customer hits that endpoint.\n\n"
        "Route the call through providers/{ai,email,storage}.py instead.\n\n"
        + "\n".join(violations)
    )


def test_blocking_http_client_is_not_used_on_request_paths():
    """`requests` is synchronous; inside `async def` it stalls the event loop.

    One slow upload then delays every other request the process is serving,
    which turns a slow dependency into a whole-service slowdown. All outbound
    HTTP goes through async httpx.
    """
    violations = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^\s*import\s+requests\b|^\s*from\s+requests\b",
                                 source, re.MULTILINE):
            line = source.count("\n", 0, match.start()) + 1
            violations.append(f"  {path.name}:{line}")

    assert not violations, (
        "The synchronous `requests` library must not be used -- it blocks the\n"
        "event loop when called from an async handler. Use httpx.AsyncClient.\n\n"
        + "\n".join(violations)
    )


def test_server_does_not_read_vendor_credentials_directly():
    """Credentials are resolved inside the provider that needs them.

    If `server.py` reads a vendor key, the provider abstraction is being
    bypassed somewhere, even when the SDK import itself has been moved.
    """
    source = (BACKEND / "server.py").read_text(encoding="utf-8")
    leaked = [key for key in
              ("EMERGENT_LLM_KEY", "RESEND_API_KEY", "ANTHROPIC_API_KEY",
               "S3_SECRET_KEY", "S3_ACCESS_KEY")
              if re.search(rf"os\.environ.*{key}", source)]
    assert not leaked, (
        f"server.py reads vendor credentials directly: {', '.join(leaked)}.\n"
        "Each provider resolves its own credentials in providers/."
    )


class TestNullProvidersDegradeCleanly:
    """With no keys configured the app must start and serve everything else.

    A client deploying on their own account has no keys on day one. If a missing
    key raised at import or startup, they could not run the app at all.
    """

    def test_null_ai_raises_the_error_callers_already_handle(self):
        import asyncio
        from providers import ai

        provider = ai.NullAI()
        assert provider.available is False
        with pytest.raises(ai.AIUnavailable) as excinfo:
            asyncio.run(provider.chat("system", "user"))
        # The message has to tell whoever sees it in a log what to actually do.
        assert "ANTHROPIC" in str(excinfo.value).upper() or "EMERGENT" in str(excinfo.value).upper()

    def test_every_provider_module_exposes_a_null_implementation(self):
        from providers import ai, email, storage

        for module in (ai, email, storage):
            nulls = [obj for name, obj in vars(module).items()
                     if name.startswith("Null")]
            assert nulls, (
                f"providers/{module.__name__.split('.')[-1]}.py has no Null "
                f"implementation, so the app cannot start without that vendor's key."
            )
