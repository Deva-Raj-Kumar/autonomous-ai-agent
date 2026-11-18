"""Short-term memory: what the agent needs RIGHT NOW.

1. WorkingMemory     - a scratchpad for ONE task run (Phase 7 executor uses it):
                       results of finished tasks, observations, notes. Lives in RAM.
2. ConversationStore - the history of one chat session, stored in the database:
                       recent messages word-for-word plus a running summary of older ones.

Why not send the whole history every time? LLMs have a limited context window, and
every token costs money and time. A summary-plus-recent-window keeps prompts small
while keeping the gist of a long conversation ("summary buffer memory").
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, func, select, update

from app.database.connection import Database
from app.database.models import Conversation, ConversationMessage

# ------------------------------------------------------------- working memory
EntryKind = Literal["task_result", "observation", "note"]


@dataclass
class MemoryEntry:
    kind: EntryKind
    content: str
    task_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class WorkingMemory:
    """Bounded scratchpad for one agent run.

    A deque with maxlen drops the OLDEST entry automatically when full, so memory use
    can never grow without limit, even in a very long run.
    """

    def __init__(self, goal: str, *, max_entries: int = 50, max_entry_chars: int = 2_000) -> None:
        self.goal = goal
        self._entries: deque[MemoryEntry] = deque(maxlen=max_entries)
        self._max_entry_chars = max_entry_chars

    def add(self, kind: EntryKind, content: str, task_id: str | None = None) -> None:
        if len(content) > self._max_entry_chars:
            content = content[: self._max_entry_chars] + " ...[cut]"
        self._entries.append(MemoryEntry(kind=kind, content=content, task_id=task_id))

    def entries(self, task_ids: set[str] | None = None) -> list[MemoryEntry]:
        """All entries, or only those belonging to the given tasks."""
        return [e for e in self._entries if task_ids is None or e.task_id in task_ids]

    def task_result(self, task_id: str) -> str | None:
        """The latest result recorded for a task (what a dependent task needs)."""
        for entry in reversed(self._entries):
            if entry.kind == "task_result" and entry.task_id == task_id:
                return entry.content
        return None

    def render(self, *, max_chars: int = 6_000, task_ids: set[str] | None = None) -> str:
        """Format entries for a prompt. If too long, the OLDEST entries are dropped first."""
        lines = [
            f"[{e.kind}{' ' + e.task_id if e.task_id else ''}] {e.content}"
            for e in self.entries(task_ids)
        ]
        kept: list[str] = []
        used = 0
        for line in reversed(lines):  # newest first, so the newest survive the cut
            if used + len(line) > max_chars:
                break
            kept.append(line)
            used += len(line) + 1
        return "\n".join(reversed(kept)) if kept else "(nothing yet)"

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# --------------------------------------------------------- conversation store
@dataclass
class StoredMessage:
    id: int
    role: str
    content: str
    created_at: datetime


@dataclass
class ConversationContext:
    summary: str
    recent: list[StoredMessage]


class ConversationStore:
    """Chat history per session, in the database. Public methods are async; the
    synchronous SQLAlchemy work runs in a worker thread (same pattern as the DB tools)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        await asyncio.to_thread(self._add_message, session_id, role, content)

    async def get_context(self, session_id: str, recent_limit: int) -> ConversationContext:
        return await asyncio.to_thread(self._get_context, session_id, recent_limit)

    async def history(self, session_id: str, limit: int = 100) -> list[StoredMessage]:
        return await asyncio.to_thread(self._history, session_id, limit)

    async def count_unsummarized(self, session_id: str) -> int:
        return await asyncio.to_thread(self._count_unsummarized, session_id)

    async def oldest_unsummarized(self, session_id: str, keep_recent: int) -> list[StoredMessage]:
        return await asyncio.to_thread(self._oldest_unsummarized, session_id, keep_recent)

    async def save_summary(self, session_id: str, summary: str, message_ids: list[int]) -> None:
        await asyncio.to_thread(self._save_summary, session_id, summary, message_ids)

    async def delete_session(self, session_id: str) -> bool:
        return await asyncio.to_thread(self._delete_session, session_id)

    # ----------------------------------------------------- sync implementation
    # The API's session id is stored in conversations.session_key; messages point at the
    # conversation's numeric id (your schema's BIGINT primary key).
    # Session ids are unique PER USER, so every lookup includes the owner: user B asking
    # for session "default" gets B's session (or none), never A's.
    def _conversation(self, s, session_id: str) -> Conversation | None:
        return s.scalars(
            select(Conversation).where(
                Conversation.session_key == session_id, Conversation.user_id == self._db.current_user_id()
            )
        ).first()

    def _conversation_id(self, s, session_id: str) -> int | None:
        conversation = self._conversation(s, session_id)
        return conversation.id if conversation is not None else None

    def _add_message(self, session_id: str, role: str, content: str) -> None:
        user_id = self._db.current_user_id()
        now = datetime.now(UTC)
        with self._db.session() as s:
            conversation = self._conversation(s, session_id)
            if conversation is None:  # first message creates the session
                conversation = Conversation(
                    user_id=user_id, session_key=session_id, summary="", status="active",
                    title=content[:255] if role == "user" else None,  # first question = title
                )
                s.add(conversation)
                s.flush()  # assigns conversation.id
            conversation.updated_at = now
            s.add(ConversationMessage(conversation_id=conversation.id, role=role, content=content))

    def _get_context(self, session_id: str, recent_limit: int) -> ConversationContext:
        with self._db.session() as s:
            conversation = self._conversation(s, session_id)
            if conversation is None:
                return ConversationContext(summary="", recent=[])
            rows = s.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation.id,
                    ConversationMessage.summarized.is_(False),
                )
                .order_by(ConversationMessage.id.desc())
                .limit(recent_limit)
            ).all()
            summary = conversation.summary or ""
        recent = [_to_stored(r) for r in reversed(rows)]  # back to oldest -> newest
        return ConversationContext(summary=summary, recent=recent)

    def _history(self, session_id: str, limit: int) -> list[StoredMessage]:
        with self._db.session() as s:
            conversation_id = self._conversation_id(s, session_id)
            if conversation_id is None:
                return []
            rows = s.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.id.desc())
                .limit(limit)
            ).all()
        return [_to_stored(r) for r in reversed(rows)]

    def _count_unsummarized(self, session_id: str) -> int:
        with self._db.session() as s:
            conversation_id = self._conversation_id(s, session_id)
            if conversation_id is None:
                return 0
            return s.scalar(
                select(func.count()).where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.summarized.is_(False),
                )
            ) or 0

    def _oldest_unsummarized(self, session_id: str, keep_recent: int) -> list[StoredMessage]:
        """Unsummarized messages EXCEPT the newest `keep_recent` ones."""
        with self._db.session() as s:
            conversation_id = self._conversation_id(s, session_id)
            if conversation_id is None:
                return []
            rows = s.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.summarized.is_(False),
                )
                .order_by(ConversationMessage.id.asc())
            ).all()
        return [_to_stored(r) for r in rows[: max(0, len(rows) - keep_recent)]]

    def _save_summary(self, session_id: str, summary: str, message_ids: list[int]) -> None:
        with self._db.session() as s:  # one transaction: both changes happen, or neither
            conversation = self._conversation(s, session_id)
            if conversation is None:
                return
            conversation.summary = summary
            conversation.updated_at = datetime.now(UTC)
            s.execute(
                update(ConversationMessage)
                .where(ConversationMessage.id.in_(message_ids))
                .values(summarized=True)
            )

    def _delete_session(self, session_id: str) -> bool:
        with self._db.session() as s:
            conversation_id = self._conversation_id(s, session_id)
            if conversation_id is None:
                return False
            # Children first: your original foreign keys have no ON DELETE CASCADE,
            # and SQLite ignores cascades unless they are switched on.
            s.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id))
            s.execute(delete(Conversation).where(Conversation.id == conversation_id))
            return True


def _to_stored(row: ConversationMessage) -> StoredMessage:
    return StoredMessage(id=row.id, role=row.role, content=row.content, created_at=row.created_at)
