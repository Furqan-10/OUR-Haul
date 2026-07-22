"""Transactional email: defect alerts, reminders, invitations, audit packs.

Previously each caller did `import resend; resend.api_key = os.environ[...]`
inline -- six copies of the same setup, each with its own try/except, and the
provider named in the middle of business logic.

Sending is best-effort by design and that is preserved: a defect report must be
recorded even when the notification cannot be delivered. Failures are logged and
returned as a result object rather than raised, so callers keep working
unchanged.
"""
import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EmailResult:
    sent: bool
    message_id: Optional[str] = None
    error: str = ""


@dataclass
class Attachment:
    filename: str
    content: bytes
    content_type: str = "application/pdf"


class EmailProvider(ABC):
    name = "abstract"

    @abstractmethod
    async def send(self, to: List[str], subject: str, html: str,
                   attachments: Optional[List[Attachment]] = None) -> EmailResult:
        ...


class ResendEmail(EmailProvider):
    """Resend (current default)."""

    name = "resend"

    def __init__(self, api_key: str, sender: str):
        self.api_key, self.sender = api_key, sender

    async def send(self, to, subject, html, attachments=None) -> EmailResult:
        try:
            import resend
        except ImportError:
            # Deliberately absent from requirements-local.txt; the app must
            # still run locally without it.
            return EmailResult(False, error="resend package is not installed")

        resend.api_key = self.api_key
        params = {"from": self.sender, "to": to, "subject": subject, "html": html}
        if attachments:
            import base64
            params["attachments"] = [
                {"filename": a.filename,
                 "content": base64.b64encode(a.content).decode()}
                for a in attachments
            ]
        try:
            # The Resend SDK is synchronous; keep it off the event loop.
            result = await asyncio.to_thread(resend.Emails.send, params)
            mid = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            return EmailResult(True, message_id=mid)
        except Exception as e:
            logging.error(f"Email send failed: {e}")
            return EmailResult(False, error=str(e))


class NullEmail(EmailProvider):
    """Records what would have been sent, and sends nothing.

    Used when no API key is configured. Logs the recipient and subject so local
    flows can still be followed end to end.
    """

    name = "null"

    def __init__(self):
        self.outbox: List[dict] = []

    async def send(self, to, subject, html, attachments=None) -> EmailResult:
        self.outbox.append({"to": to, "subject": subject,
                            "attachments": [a.filename for a in (attachments or [])]})
        logging.info(f"[null email] would send to {to}: {subject}")
        return EmailResult(False, error="email is not configured (null provider)")


_provider: Optional[EmailProvider] = None


def get_provider() -> EmailProvider:
    global _provider
    if _provider is not None:
        return _provider

    choice = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("SENDER_EMAIL", "").strip()

    if choice == "null" or (not choice and not api_key):
        _provider = NullEmail()
        logging.info("Email provider: null (no RESEND_API_KEY configured)")
    else:
        _provider = ResendEmail(api_key, sender)
        logging.info("Email provider: resend")
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
