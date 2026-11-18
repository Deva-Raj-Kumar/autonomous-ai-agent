"""Gmail Service: Handles real email delivery using the official Google Gmail REST API.

Architecture:
  Gemini Email Generator -> Email Draft + Human Approval -> Gmail API (users.messages.send)
  -> Actual Gmail Sending -> Save Gmail Message ID + Status

Endpoint:
  POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send
Scope:
  https://www.googleapis.com/auth/gmail.send
"""

import base64
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailSendResult(BaseModel):
    success: bool = True
    message_id: str | None = None
    thread_id: str | None = None
    recipient: list[str] = Field(default_factory=list)
    subject: str = ""
    timestamp: str = ""
    status: str = "sent"
    detail: str = ""


class GmailAPIError(Exception):
    """Raised when Gmail API returns an authentication or dispatch failure."""


class GmailService:
    """Manages OAuth 2.0 authentication, duplicate protection, and users.messages.send dispatch."""

    def __init__(self, database: Any = None, settings: Any = None) -> None:
        self._db = database
        self._settings = settings
        self._access_token: str | None = None
        # In-memory deduplication cache: hash -> message_id
        self._sent_cache: dict[str, str] = {}

    def _message_hash(self, to: list[str], subject: str, body: str) -> str:
        """Create a fingerprint to prevent accidental duplicate sends."""
        raw = f"{sorted(to)}|{subject.strip()}|{body.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def resolve_access_token(self) -> str | None:
        """Resolve Google OAuth 2.0 access token with gmail.send permission.

        Order of resolution:
          0. In-memory cached token (if refreshed during current run)
          1. Explicit settings or environment variables (GMAIL_ACCESS_TOKEN)
          2. token.json on disk (standard Google OAuth credentials)
          3. Automatic refresh token flow using client_id + client_secret + refresh_token
        """
        if self._access_token:
            return self._access_token

        # 0. Settings object if passed
        if self._settings and getattr(self._settings, "gmail_access_token", None):
            val = self._settings.gmail_access_token.get_secret_value()
            if val and val.strip():
                return val.strip()

        # 1. Environment variable
        for key in ("GMAIL_ACCESS_TOKEN", "GMAIL_API_TOKEN", "GOOGLE_OAUTH_TOKEN", "GOOGLE_ACCESS_TOKEN"):
            val = os.getenv(key)
            if val and val.strip():
                return val.strip()

        # 2. Local token.json file from Google OAuth flow
        search_paths = [
            Path("token.json"),
            Path("data/token.json"),
            Path(".gmail_token.json"),
            Path("credentials.json"),
        ]
        for path in search_paths:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    token = data.get("token") or data.get("access_token")
                    if token:
                        return str(token).strip()
                except Exception as exc:
                    logger.debug("Could not read token from %s: %s", path, exc)

        # 3. Refresh token exchange
        return self._refresh_access_token()

    def _refresh_access_token(self) -> str | None:
        """Exchange refresh token for a fresh access token."""
        refresh_token = (
            (self._settings.gmail_refresh_token.get_secret_value() if self._settings and getattr(self._settings, "gmail_refresh_token", None) else None)
            or os.getenv("GMAIL_REFRESH_TOKEN")
            or os.getenv("GOOGLE_REFRESH_TOKEN")
        )
        client_id = (
            (getattr(self._settings, "google_client_id", None) if self._settings else None)
            or os.getenv("GOOGLE_CLIENT_ID")
            or os.getenv("GMAIL_CLIENT_ID")
        )
        client_secret = (
            (self._settings.google_client_secret.get_secret_value() if self._settings and getattr(self._settings, "google_client_secret", None) else None)
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or os.getenv("GMAIL_CLIENT_SECRET")
        )

        if refresh_token and client_id and client_secret:
            try:
                resp = requests.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    token_data = resp.json()
                    new_token = token_data.get("access_token")
                    if new_token:
                        self._access_token = str(new_token).strip()
                        logger.info("Successfully refreshed Gmail OAuth 2.0 access token")
                        return self._access_token
            except Exception as exc:
                logger.warning("Failed to refresh Gmail OAuth token: %s", exc)

        return None

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        sender: str | None = None,
    ) -> GmailSendResult:
        """Send an email using Gmail API users.messages.send.

        Enforces:
          - Human approval already happened before calling this
          - Duplicate send prevention
          - OAuth 2.0 authentication check
          - RFC 2822 base64url encoding
          - Gmail API response verification (must return 200 with message id)
          - Database persistence of message ID and status
        """
        # Deduplication check
        msg_hash = self._message_hash(to, subject, body)
        if msg_hash in self._sent_cache:
            existing_id = self._sent_cache[msg_hash]
            logger.info("Duplicate send prevented for message (existing ID: %s)", existing_id)
            return GmailSendResult(
                success=True,
                message_id=existing_id,
                recipient=to,
                subject=subject,
                timestamp=datetime.now(UTC).isoformat(),
                status="sent (deduplicated)",
                detail=f"Email was already sent via Gmail API (Message ID: {existing_id}). Prevented duplicate dispatch.",
            )

        token = self.resolve_access_token()
        if not token:
            raise GmailAPIError(
                "Gmail API authentication required: No valid OAuth 2.0 token found. "
                "Please configure GMAIL_ACCESS_TOKEN in .env or provide an authorized token.json "
                "with the 'https://www.googleapis.com/auth/gmail.send' scope."
            )

        # Build RFC 2822 standard email message
        message = EmailMessage()
        message["From"] = sender or os.getenv("GMAIL_USER") or "me"
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
        message.set_content(body)

        # Base64url encode the message bytes (as required by Gmail API)
        raw_b64 = base64.urlsafe_b64encode(bytes(message)).decode("ascii")

        try:
            response = requests.post(
                GMAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw_b64},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise GmailAPIError(f"Network error communicating with Gmail API: {exc}") from exc

        if response.status_code == 200:
            res_data = response.json()
            message_id = res_data.get("id")
            thread_id = res_data.get("threadId")
            now_iso = datetime.now(UTC).isoformat()

            # Record in deduplication cache
            if message_id:
                self._sent_cache[msg_hash] = message_id

            # Save Gmail Message ID and status in database
            self._save_to_database(
                to=to,
                subject=subject,
                body=body,
                message_id=message_id,
                thread_id=thread_id,
                timestamp=now_iso,
                status="sent",
            )

            logger.info("Successfully sent email via Gmail API: ID=%s, To=%s", message_id, to)
            return GmailSendResult(
                success=True,
                message_id=message_id,
                thread_id=thread_id,
                recipient=to,
                subject=subject,
                timestamp=now_iso,
                status="sent",
                detail=f"Email successfully sent via Gmail API users.messages.send! Message ID: {message_id}.",
            )

        # Handle specific Gmail API errors
        if response.status_code in (401, 403):
            err_msg = response.json().get("error", {}).get("message", response.text)
            raise GmailAPIError(
                f"Gmail API authorization error ({response.status_code}): {err_msg}. "
                "Verify your OAuth token has 'https://www.googleapis.com/auth/gmail.send' permission."
            )

        raise GmailAPIError(f"Gmail API failed ({response.status_code}): {response.text}")

    def _save_to_database(
        self,
        to: list[str],
        subject: str,
        body: str,
        message_id: str | None,
        thread_id: str | None,
        timestamp: str,
        status: str,
    ) -> None:
        """Persist Gmail message ID, recipient, subject, and status to the database."""
        if self._db is None:
            return
        try:
            from app.database.models import SavedRecord

            user_id = self._db.current_user_id()
            record_data = {
                "gmail_message_id": message_id,
                "thread_id": thread_id,
                "recipient": to,
                "subject": subject,
                "body_snippet": body[:300],
                "status": status,
                "timestamp": timestamp,
                "provider": "Gmail API (users.messages.send)",
            }
            with self._db.session() as session:
                session.add(
                    SavedRecord(
                        user_id=user_id,
                        kind="note",
                        title=f"Gmail Sent: {subject} -> {', '.join(to)}",
                        content=json.dumps(record_data, indent=2),
                    )
                )
            logger.info("Saved Gmail dispatch record to database for Message ID: %s", message_id)
        except Exception as exc:
            logger.warning("Could not persist Gmail record to database: %s", exc)
