"""SQLAlchemy model and schemas for Email Records and Gmail API state machine."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID = BigInteger().with_variant(Integer(), "sqlite")
LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


class EmailBase(DeclarativeBase):
    """Declarative base for email tracking tables."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def email_created_column() -> Any:
    return mapped_column(TIMESTAMP, default=utc_now, server_default=func.current_timestamp(), nullable=True)


class EmailStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class EmailRecord(EmailBase):
    """Stores full lifecycle and tracking of emails generated, approved, and dispatched."""

    __tablename__ = "email_records"
    __table_args__ = (
        Index("ix_email_records_user_id", "user_id"),
        Index("ix_email_records_operation_id", "operation_id"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    email_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ID)
    recipient: Mapped[str] = mapped_column(String(500))
    cc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bcc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(LONG_TEXT)
    body_html: Mapped[str | None] = mapped_column(LONG_TEXT, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=EmailStatus.DRAFT.value, index=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = email_created_column()
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "email_id": self.email_id,
            "user_id": self.user_id,
            "recipient": [r.strip() for r in self.recipient.split(",") if r.strip()],
            "cc": [r.strip() for r in self.cc.split(",") if r.strip()] if self.cc else [],
            "bcc": [r.strip() for r in self.bcc.split(",") if r.strip()] if self.bcc else [],
            "subject": self.subject,
            "body": self.body,
            "body_html": self.body_html,
            "status": self.status,
            "gmail_message_id": self.gmail_message_id,
            "thread_id": self.thread_id,
            "operation_id": self.operation_id,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }
