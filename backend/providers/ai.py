"""AI: defect summaries, letter drafting, insurance import, fleet risk briefing,
tacho printout analysis.

`emergentintegrations` was imported inline at seven call sites and is not on
PyPI, so every AI feature was unavailable outside the Emergent image -- and
untestable anywhere else. This wraps it, adds a direct Anthropic implementation
as the migration path, and a null provider that degrades cleanly.

Callers already treat AI as best-effort (each site has a try/except and a
fallback), so `AIUnavailable` fits the existing error handling.
"""
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class AIUnavailable(RuntimeError):
    """No AI backend is configured or reachable."""


@dataclass
class FileInput:
    """An image or PDF passed alongside the prompt (tacho printouts,
    insurance certificates)."""
    content: bytes
    content_type: str
    filename: str = ""


class AIProvider(ABC):
    name = "abstract"

    @abstractmethod
    async def chat(self, system: str, user: str, *, files: Optional[List[FileInput]] = None,
                   session_id: str = "", model_hint: str = "") -> str:
        """Return the model's text response."""

    @property
    def available(self) -> bool:
        return True


class EmergentLLM(AIProvider):
    """Emergent's hosted LLM gateway (current default)."""

    name = "emergent"

    def __init__(self, key: str):
        self.key = key

    async def chat(self, system, user, *, files=None, session_id="", model_hint="") -> str:
        try:
            from emergentintegrations.llm.chat import (
                LlmChat, UserMessage, ImageContent, FileContentWithMimeType,
            )
        except ImportError:
            raise AIUnavailable(
                "emergentintegrations is not installed (it is not published on PyPI). "
                "AI features require the Emergent runtime, or set AI_PROVIDER=anthropic."
            )

        import base64
        import os as _os
        import tempfile

        chat = LlmChat(api_key=self.key, session_id=session_id or "haulcheck",
                       system_message=system)
        # Preserves the original model selection: images to a vision model,
        # PDFs to a long-context one.
        provider, model = ("openai", "gpt-5.4")
        if model_hint:
            provider, _, model = model_hint.partition(":")
        chat = chat.with_model(provider, model)

        # `FileContentWithMimeType` reads from disk, so non-image input has to be
        # spilled to a temp file. Doing it here rather than at the call sites
        # keeps `FileInput` uniformly bytes-based -- callers should not have to
        # know that one provider wants a path and another wants base64, nor
        # repeat the cleanup. Anything written here is removed in `finally`.
        contents, temps = [], []
        try:
            for f in files or []:
                if f.content_type.startswith("image/"):
                    contents.append(ImageContent(
                        image_base64=base64.b64encode(f.content).decode()))
                else:
                    suffix = _os.path.splitext(f.filename)[1] or ".pdf"
                    fd, path = tempfile.mkstemp(suffix=suffix)
                    with _os.fdopen(fd, "wb") as fh:
                        fh.write(f.content)
                    temps.append(path)
                    contents.append(FileContentWithMimeType(
                        file_path=path, mime_type=f.content_type or "application/pdf"))
            message = UserMessage(text=user, file_contents=contents or None)
            return await chat.send_message(message)
        finally:
            for path in temps:
                try:
                    _os.unlink(path)
                except OSError:
                    pass


class AnthropicAI(AIProvider):
    """Direct Anthropic API — the migration path off the Emergent gateway.

    Uses the `anthropic` package, which is on PyPI and installable anywhere, so
    AI features become testable outside the platform image. Enable with
    AI_PROVIDER=anthropic and ANTHROPIC_API_KEY.
    """

    name = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-5"

    def __init__(self, api_key: str, model: str = ""):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    async def chat(self, system, user, *, files=None, session_id="", model_hint="") -> str:
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise AIUnavailable(
                "The 'anthropic' package is not installed. Add it to requirements "
                "to use AI_PROVIDER=anthropic."
            )
        import base64

        client = AsyncAnthropic(api_key=self.api_key)
        content = []
        for f in files or []:
            b64 = base64.b64encode(f.content).decode()
            if f.content_type.startswith("image/"):
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": f.content_type, "data": b64}})
            elif f.content_type == "application/pdf":
                content.append({"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf", "data": b64}})
        content.append({"type": "text", "text": user})

        resp = await client.messages.create(
            model=self.model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": content}])
        return "".join(block.text for block in resp.content if block.type == "text")


class NullAI(AIProvider):
    """No AI configured. Raises a clear error the existing handlers already catch."""

    name = "null"

    @property
    def available(self) -> bool:
        return False

    async def chat(self, system, user, *, files=None, session_id="", model_hint="") -> str:
        raise AIUnavailable(
            "AI features are not configured. Set EMERGENT_LLM_KEY, or "
            "AI_PROVIDER=anthropic with ANTHROPIC_API_KEY."
        )


_provider: Optional[AIProvider] = None


def get_provider() -> AIProvider:
    global _provider
    if _provider is not None:
        return _provider

    choice = (os.environ.get("AI_PROVIDER") or "").strip().lower()
    if choice == "anthropic":
        _provider = AnthropicAI(os.environ["ANTHROPIC_API_KEY"],
                                os.environ.get("ANTHROPIC_MODEL", ""))
    elif choice == "null" or (not choice and not os.environ.get("EMERGENT_LLM_KEY", "").strip()):
        _provider = NullAI()
        logging.info("AI provider: null (no key configured)")
    else:
        _provider = EmergentLLM(os.environ.get("EMERGENT_LLM_KEY", ""))
    logging.info(f"AI provider: {_provider.name}")
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
