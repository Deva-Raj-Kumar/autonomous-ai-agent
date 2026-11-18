"""Email tool: Dispatches emails via Gmail API (users.messages.send), live SMTP, or local outbox.

Safety layers:
  1. catalog:     requires_approval=True, so human approves every email
  2. approval:    human sees exact recipients, subject, and body before approving
  3. permissions: recipient must be on EMAIL_ALLOWED_RECIPIENTS
  4. budgets:     rate limits and call budgets enforced per run
"""

import asyncio
import logging
import os
import re
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.services.gmail_service import GmailAPIError, GmailService
from app.tools.base import AgentTool, ToolError

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
SENDER = "agent@localhost"


class EmailInput(BaseModel):
    to: list[str] = Field(min_length=1, max_length=5, description="Recipient email addresses.")
    subject: str = Field(min_length=1, max_length=150, description="Email subject line.")
    body: str = Field(min_length=1, max_length=10_000, description="Plain-text email body.")

    @field_validator("to")
    @classmethod
    def _valid_addresses(cls, addresses: list[str]) -> list[str]:
        cleaned = [a.strip() for a in addresses]
        bad = [a for a in cleaned if not EMAIL_PATTERN.match(a)]
        if bad:
            raise ValueError(f"invalid email address(es): {', '.join(bad)}")
        return cleaned

    @field_validator("subject")
    @classmethod
    def _single_line_subject(cls, subject: str) -> str:
        if "\n" in subject or "\r" in subject:
            raise ValueError("subject must be a single line")
        return subject


class SendEmailTool(AgentTool):
    name = "send_email"
    input_model = EmailInput

    def __init__(self, outbox_dir: Path, database: Any = None) -> None:
        self._outbox = outbox_dir
        self._db = database
        self._gmail = GmailService(database=database)

    async def run(self, args: EmailInput) -> str:  # type: ignore[override]
        return await asyncio.to_thread(self._deliver, args)

    def _deliver(self, args: EmailInput) -> str:
        # Build standard RFC 2822 MIME message
        smtp_user = os.getenv("SMTP_USER") or os.getenv("GMAIL_USER")
        sender = smtp_user if smtp_user else SENDER

        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(args.to)
        message["Subject"] = args.subject
        message["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
        message.set_content(args.body)

        # Always archive to outbox for audit tracking
        self._outbox.mkdir(parents=True, exist_ok=True)
        archive_path = self._outbox / f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.eml"
        archive_path.write_bytes(bytes(message))

        # Determine delivery mode: "gmail" vs "outbox"
        email_mode = os.getenv("EMAIL_MODE", "outbox").strip().lower()

        # In outbox mode: archive and return explicitly
        if email_mode == "outbox":
            return (
                f"Email to {', '.join(args.to)} saved to the outbox ({archive_path.name}); "
                f"outbox mode: not actually sent."
            )

        # In gmail mode: require live delivery via Gmail API or SMTP; NEVER fall back to outbox
        # 1. Check if Gmail API OAuth 2.0 (users.messages.send) is configured
        if self._gmail.resolve_access_token():
            try:
                res = self._gmail.send_email(to=args.to, subject=args.subject, body=args.body, sender=sender)
                return res.detail
            except GmailAPIError as exc:
                raise ToolError(f"Gmail API delivery failed: {exc}") from exc

        # 2. Check if live SMTP (Gmail App Password or SMTP server) is configured
        smtp_password = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))

        if smtp_user and smtp_password:
            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.send_message(message)
                logger.info("Email sent via SMTP to %s", args.to)
                return (
                    f"Email successfully dispatched to {', '.join(args.to)} via Gmail/SMTP "
                    f"(Subject: '{args.subject}'). Copy archived in outbox ({archive_path.name})."
                )
            except Exception as exc:
                logger.error("Failed to send email via SMTP (%s): %s", type(exc).__name__, exc)
                raise ToolError(f"SMTP delivery failed: {exc}") from exc

        # Gmail mode is active but credentials are missing: raise clear configuration error
        raise ToolError(
            "Gmail API configuration missing. Please authenticate with Google OAuth 2.0 "
            "(scope: https://www.googleapis.com/auth/gmail.send) or configure GMAIL_ACCESS_TOKEN / SMTP in .env."
        )
