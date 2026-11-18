"""Email Agent: Autonomous parsing, draft generation via Gemini LLM,
approval validation, idempotency guard, and Gmail API dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select

from app.config import Settings
from app.database.connection import Database
from app.database.email_models import EmailRecord, EmailStatus
from app.llm.service import LLMService
from app.services.gmail_service import GmailAPIError, GmailService

logger = logging.getLogger(__name__)

EMAIL_SYSTEM_PROMPT = """You are an intelligent autonomous email agent.
Given the user's instruction, generate a professional, high-quality email.
Rules:
1. Extract or determine appropriate recipient(s). If none specified in prompt, use the provided fallback recipient.
2. Generate a concise, clear subject line.
3. Write a well-structured, courteous body (with greeting, message, and sign-off).
4. Return ONLY a valid JSON object with keys:
   - "to": list of strings (email addresses)
   - "subject": string
   - "body": string (plain text)
   - "body_html": string (optional HTML version)
Do not include markdown code fence formatting.
"""


class EmailAgent:
    """Orchestrates natural language parsing, drafting, approval, and sending."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        llm_service: LLMService | None = None,
        gmail_service: GmailService | None = None,
    ) -> None:
        self.db = database
        self.settings = settings
        self.llm = llm_service
        self.gmail = gmail_service or GmailService(settings=settings, database=database)

    async def draft_email(
        self,
        *,
        user_id: int,
        prompt: str | None = None,
        to: list[str] | None = None,
        subject: str | None = None,
        body: str | None = None,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> EmailRecord:
        """Create an email draft with status PENDING_APPROVAL.
        Uses Gemini LLM if prompt is provided and subject/body are empty.
        """
        recipients = list(to or [])
        subj = subject or ""
        text_body = body or ""
        html_body = body_html

        # Generate via LLM if prompt provided
        if prompt and (not subj or not text_body):
            generated = await self._generate_draft_content(prompt, fallback_to=recipients)
            recipients = generated.get("to") or recipients
            subj = generated.get("subject") or subj or "Inquiry"
            text_body = generated.get("body") or text_body or prompt
            html_body = generated.get("body_html") or html_body

        if not recipients:
            raise ValueError("Recipient email address is required to create a draft.")

        email_id = f"eml_{uuid4().hex[:16]}"
        record = EmailRecord(
            email_id=email_id,
            user_id=user_id,
            recipient=", ".join(recipients),
            cc=", ".join(cc) if cc else None,
            bcc=", ".join(bcc) if bcc else None,
            subject=subj,
            body=text_body,
            body_html=html_body,
            status=EmailStatus.PENDING_APPROVAL.value,
        )

        with self.db.session() as session:
            session.add(record)

        logger.info("Created draft email %s for user %s (status: %s)", email_id, user_id, record.status)
        return record

    async def _generate_draft_content(self, prompt: str, fallback_to: list[str]) -> dict[str, Any]:
        """Calls Gemini LLM to construct structured email parameters."""
        if not self.llm:
            return {
                "to": fallback_to or ["hr@techcorp.in"],
                "subject": f"Regarding: {prompt[:40]}",
                "body": prompt,
            }

        user_msg = (
            f"Instruction: {prompt}\n"
            f"Fallback recipients: {fallback_to}\n"
            "Return JSON with: to, subject, body, body_html"
        )
        try:
            # Check if LLM has structured generation or call direct
            raw_response = await asyncio.to_thread(self._sync_call_llm, user_msg)
            # Clean possible markdown ```json ... ```
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            data = json.loads(cleaned.strip())
            return {
                "to": data.get("to") or fallback_to,
                "subject": data.get("subject", "Inquiry"),
                "body": data.get("body", prompt),
                "body_html": data.get("body_html"),
            }
        except Exception as exc:
            logger.warning("LLM draft generation failed (%s), using fallback", exc)
            return {
                "to": fallback_to or ["devarajkumar155@gmail.com"],
                "subject": f"Inquiry regarding {prompt[:30]}",
                "body": prompt,
            }

    def _sync_call_llm(self, prompt: str) -> str:
        if hasattr(self.llm, "complete"):
            return str(self.llm.complete(f"{EMAIL_SYSTEM_PROMPT}\n\n{prompt}"))
        if hasattr(self.llm, "model") and hasattr(self.llm.model, "invoke"):
            res = self.llm.model.invoke(f"{EMAIL_SYSTEM_PROMPT}\n\n{prompt}")
            return getattr(res, "content", str(res))
        return json.dumps({
            "subject": "Follow-up",
            "body": prompt,
        })

    def approve_email(self, email_id: str, user_id: int) -> EmailRecord:
        """Transition status from pending_approval/draft to approved."""
        with self.db.session() as session:
            record = session.scalar(
                select(EmailRecord).where(EmailRecord.email_id == email_id, EmailRecord.user_id == user_id)
            )
            if not record:
                raise ValueError(f"Email record '{email_id}' not found.")
            if record.status not in (EmailStatus.PENDING_APPROVAL.value, EmailStatus.DRAFT.value):
                raise ValueError(f"Cannot approve email in status: {record.status}")
            record.status = EmailStatus.APPROVED.value
            session.add(record)
            session.flush()
            return record

    def reject_email(self, email_id: str, user_id: int, reason: str = "") -> EmailRecord:
        """Reject draft email."""
        with self.db.session() as session:
            record = session.scalar(
                select(EmailRecord).where(EmailRecord.email_id == email_id, EmailRecord.user_id == user_id)
            )
            if not record:
                raise ValueError(f"Email record '{email_id}' not found.")
            record.status = EmailStatus.REJECTED.value
            if reason:
                record.error_message = reason
            session.add(record)
            session.flush()
            return record

    async def send_email(
        self,
        email_id: str,
        user_id: int,
        operation_id: str | None = None,
    ) -> EmailRecord:
        """Dispatches an approved email via Gmail API or outbox."""
        op_id = operation_id or f"op_{uuid4().hex[:12]}"

        # 1. Verification and state transition to SENDING
        with self.db.session() as session:
            record = session.scalar(
                select(EmailRecord).where(EmailRecord.email_id == email_id, EmailRecord.user_id == user_id)
            )
            if not record:
                raise ValueError(f"Email record '{email_id}' not found.")
            if record.status == EmailStatus.SENT.value:
                logger.info("Email %s was already sent (idempotent no-op).", email_id)
                return record
            if record.status != EmailStatus.APPROVED.value:
                raise ValueError(
                    f"Email cannot be dispatched in status '{record.status}'. Approval is strictly required."
                )

            # Prevent duplicate concurrency
            record.status = EmailStatus.SENDING.value
            record.operation_id = op_id
            session.add(record)

        # 2. Dispatch
        mode = self.settings.email_mode
        recipients = [r.strip() for r in record.recipient.split(",") if r.strip()]

        if mode == "gmail":
            token = self.gmail.resolve_access_token()
            if not token:
                # Update status to failed
                with self.db.session() as session:
                    r = session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))
                    if r:
                        r.status = EmailStatus.FAILED.value
                        r.error_message = "Gmail API configuration missing. Please authenticate."
                        session.add(r)
                raise RuntimeError("Gmail API configuration missing. Please authenticate.")

            try:
                # Execute send
                res = await asyncio.to_thread(
                    self.gmail.send_email,
                    to=recipients,
                    subject=record.subject,
                    body=record.body,
                    body_html=record.body_html,
                    cc=[c.strip() for c in record.cc.split(",") if c.strip()] if record.cc else None,
                    bcc=[b.strip() for b in record.bcc.split(",") if b.strip()] if record.bcc else None,
                )
                with self.db.session() as session:
                    r = session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))
                    if r:
                        r.status = EmailStatus.SENT.value
                        r.gmail_message_id = res.message_id
                        r.thread_id = res.thread_id
                        r.sent_at = datetime.now(UTC)
                        session.add(r)
                        session.flush()
                        return r
            except (TimeoutError, asyncio.TimeoutError) as exc:
                # Network timeout: mark uncertain to prevent double-send
                logger.error("Timeout during Gmail API send for %s: %s", email_id, exc)
                with self.db.session() as session:
                    r = session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))
                    if r:
                        r.status = EmailStatus.UNCERTAIN.value
                        r.error_message = f"Network timeout during Gmail send: {exc}"
                        session.add(r)
                        session.flush()
                        return r
            except Exception as exc:
                logger.error("Gmail API delivery failed for %s: %s", email_id, exc)
                with self.db.session() as session:
                    r = session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))
                    if r:
                        r.status = EmailStatus.FAILED.value
                        r.error_message = str(exc)
                        session.add(r)
                        session.flush()
                raise

        else:
            # Outbox mode
            outbox_dir = self.settings.email_outbox_dir
            outbox_dir.mkdir(parents=True, exist_ok=True)
            mock_file = outbox_dir / f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.eml"
            mock_file.write_text(
                f"To: {record.recipient}\nSubject: {record.subject}\n\n{record.body}",
                encoding="utf-8",
            )
            with self.db.session() as session:
                r = session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))
                if r:
                    r.status = EmailStatus.SENT.value
                    r.gmail_message_id = f"outbox-{mock_file.name}"
                    r.sent_at = datetime.now(UTC)
                    session.add(r)
                    session.flush()
                    return r

        # Return latest state
        with self.db.session() as session:
            return session.scalar(select(EmailRecord).where(EmailRecord.email_id == email_id))  # type: ignore

    def get_history(self, user_id: int, limit: int = 50) -> list[EmailRecord]:
        """Fetch email history for the authenticated user."""
        with self.db.session() as session:
            stmt = (
                select(EmailRecord)
                .where(EmailRecord.user_id == user_id)
                .order_by(desc(EmailRecord.created_at))
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    def get_record(self, email_id: str, user_id: int) -> EmailRecord | None:
        """Fetch a specific email record."""
        with self.db.session() as session:
            return session.scalar(
                select(EmailRecord).where(EmailRecord.email_id == email_id, EmailRecord.user_id == user_id)
            )
