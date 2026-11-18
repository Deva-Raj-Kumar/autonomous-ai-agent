"""Database tables, defined as Python classes (SQLAlchemy ORM, 2.0 style).

Each class = one table; each `Mapped[...]` attribute = one column.

The schema is YOUR MySQL design (users, conversations, memories, tasks, task_steps,
tool_logs, approvals), extended by Alembic migration 0002 with the columns the agent
needs. The migrations in alembic/versions/ are what actually create/alter tables;
these classes must stay in sync with them (tests/test_migrations.py checks that).

Notes on the types used:
  - PK / FK ids are BIGINT (your design). SQLite only auto-increments INTEGER primary
    keys, so the tests' in-memory SQLite gets INTEGER through `.with_variant()`.
  - Times are TIMESTAMP (your design), always stored in UTC: the connection sets the
    MySQL session time zone to UTC (see connection.py). TIMESTAMP's range ends in 2038.
  - LONGTEXT (up to 4 GB) on MySQL for big texts, plain TEXT elsewhere.
  - An attribute name may differ from its column name, e.g. Memory.content is stored in
    your `memory_content` column, so the rest of the app keeps its simple names.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BIGINT on MySQL; INTEGER on SQLite (so ids still auto-increment there).
ID = BigInteger().with_variant(Integer(), "sqlite")
LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


def utc_now() -> datetime:
    return datetime.now(UTC)


def created_column() -> Any:
    """TIMESTAMP set by Python on insert (UTC), with the DB default as a fallback."""
    return mapped_column(TIMESTAMP, default=utc_now, server_default=func.current_timestamp(), nullable=True)


class Base(DeclarativeBase):
    """Parent class of all tables. Base.metadata knows every table."""


# ------------------------------------------------------------------- users
class User(Base):
    """Your users table. API users log in with email + password (Phase 12); the CLI
    acts as the local user created by migration 0002."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # "!" = no usable password (local user)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime | None] = created_column()
    # --- added by migration 0003 ---
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)


class RefreshToken(Base):
    """Added by migration 0003. One row per issued refresh token, stored as a SHA-256
    HASH (a database leak doesn't leak usable tokens). Tokens of one login share a
    family_id: if an already-used token is presented again, it was stolen and replayed,
    so the whole family is revoked."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime | None] = created_column()


# ------------------------------------------------------ conversation memory
class Conversation(Base):
    __tablename__ = "conversations"
    # Session ids are chosen by clients, so two users may both pick "default":
    # unique PER USER (migration 0003), not across the whole table.
    __table_args__ = (UniqueConstraint("user_id", "session_key", name="uq_conversations_user_session"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(30), default="active", server_default="active")
    created_at: Mapped[datetime | None] = created_column()
    # --- added by migration 0002 ---
    session_key: Mapped[str] = mapped_column(String(64))  # the API's session id
    summary: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = created_column()


class ConversationMessage(Base):
    """Added by migration 0002 (your schema had no table for chat messages)."""

    __tablename__ = "conversation_messages"
    # migration 0004: FK columns need explicit indexes outside MySQL
    __table_args__ = (Index("ix_conversation_messages_conversation_id", "conversation_id"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ID, ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(LONG_TEXT)
    summarized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime | None] = created_column()


# ------------------------------------------------------- long-term memory
class Memory(Base):
    """A lasting fact about the user, e.g. 'User lives in Hyderabad.'"""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_id", "user_id"),)  # migration 0004: FK columns need explicit indexes outside MySQL

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id"))
    category: Mapped[str | None] = mapped_column("memory_type", String(50))  # column name: memory_type
    content: Mapped[str | None] = mapped_column("memory_content", LONG_TEXT)  # column name: memory_content
    # `metadata` is a reserved attribute on SQLAlchemy models, so the attribute is `meta`.
    meta: Mapped[dict | None] = mapped_column("metadata", JSON)
    # --- added by migration 0002 ---
    importance: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime | None] = created_column()
    updated_at: Mapped[datetime | None] = created_column()
    last_accessed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


# ---------------------------------------------------- agent runs (history)
class AgentRun(Base):
    """Your `tasks` table = one agent RUN (a goal). Named AgentRun in code because
    `Task` already means one plan step."""

    __tablename__ = "tasks"
    # (user_id, created_at): "my newest runs" is read straight from the index, already in order.
    __table_args__ = (Index("ix_tasks_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id"))
    conversation_id: Mapped[int | None] = mapped_column(ID, ForeignKey("conversations.id"))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(40), default="pending", server_default="pending")
    created_at: Mapped[datetime | None] = created_column()
    # --- added by migration 0002 ---
    run_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # LangGraph thread id
    final_output: Mapped[str | None] = mapped_column(LONG_TEXT)
    steps_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quality_score: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = created_column()


class RunStep(Base):
    """Your `task_steps` table = one task of a run's plan (t1, t2, ...)."""

    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_id", "step_number", name="task_id"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    task_id: Mapped[int] = mapped_column(ID, ForeignKey("tasks.id"))  # the RUN's id
    step_number: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(30), default="pending", server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSON)
    # --- added by migration 0002 ---
    step_key: Mapped[str | None] = mapped_column(String(20))  # the plan's id: "t1"
    title: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class ToolLog(Base):
    """Your `tool_logs` table = one tool attempt: the audit trail of what actually ran."""

    __tablename__ = "tool_logs"
    __table_args__ = (Index("ix_tool_logs_task_id", "task_id"),)  # migration 0004: FK columns need explicit indexes outside MySQL

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    task_id: Mapped[int] = mapped_column(ID, ForeignKey("tasks.id"))  # the RUN's id
    tool_name: Mapped[str | None] = mapped_column(String(100))
    input_data: Mapped[dict | None] = mapped_column(JSON)
    output_data: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(30))
    execution_time_ms: Mapped[int | None] = mapped_column(Integer)
    # --- added by migration 0002 ---
    step_key: Mapped[str | None] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = created_column()


class ApprovalRecord(Base):
    """Your `approvals` table: one human-approval request and its decision."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_task_id", "task_id"),)  # migration 0004: FK columns need explicit indexes outside MySQL

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    task_id: Mapped[int] = mapped_column(ID, ForeignKey("tasks.id"))  # the RUN's id
    action_name: Mapped[str | None] = mapped_column(String(100))  # the tool, e.g. "send_email"
    action_details: Mapped[dict | None] = mapped_column(JSON)  # {"title": ..., "arguments": {...}}
    status: Mapped[str | None] = mapped_column(String(30), default="pending", server_default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)  # time of the decision
    # --- added by migration 0002 ---
    step_key: Mapped[str | None] = mapped_column(String(20))  # which plan task ("t2")
    arguments_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 of the exact arguments
    requested_at: Mapped[datetime | None] = created_column()
    decided_by: Mapped[str | None] = mapped_column(String(100))


# ------------------------------------------------------------ saved records
class SavedRecord(Base):
    """Added by migration 0002: what the save_to_database / database_query tools use."""

    __tablename__ = "saved_records"
    # migration 0004: FK columns need explicit indexes outside MySQL
    __table_args__ = (Index("ix_saved_records_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(LONG_TEXT)
    created_at: Mapped[datetime | None] = created_column()

    def __repr__(self) -> str:
        return f"SavedRecord(id={self.id}, kind={self.kind!r}, title={self.title!r})"

