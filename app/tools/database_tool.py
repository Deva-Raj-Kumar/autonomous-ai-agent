"""Database tools: save a record, and search saved records.

SECURITY RULE: the LLM never writes SQL. If it could send raw SQL, one prompt injection
("...then run DROP TABLE saved_records") could destroy data. Instead each tool offers a
narrow, typed operation, and SQLAlchemy sends values as bound PARAMETERS, never by
pasting text into the SQL string. That is what prevents SQL injection.
"""

import asyncio
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.database.connection import Database
from app.database.models import SavedRecord
from app.llm.prompts import wrap_untrusted
from app.tools.base import AgentTool, ToolError

RecordKind = Literal["report", "research", "note", "application", "job"]
PREVIEW_CHARS = 300


class SaveInput(BaseModel):
    kind: RecordKind = Field(description="Type of record: report, research, note, application, or job.")
    title: str = Field(min_length=1, max_length=200, description="Short descriptive title.")
    content: str = Field(min_length=1, max_length=100_000, description="The full text to save.")


class SaveToDatabaseTool(AgentTool):
    name = "save_to_database"
    input_model = SaveInput

    def __init__(self, database: Database) -> None:
        self._db = database

    async def run(self, args: SaveInput) -> str:  # type: ignore[override]
        # SQLAlchemy here is synchronous, so run it in a thread (keeps the event loop free).
        record_id = await asyncio.to_thread(self._save, args)
        return f"Saved {args.kind} #{record_id}: '{args.title}' ({len(args.content)} characters)."

    def _save(self, args: SaveInput) -> int:
        user_id = self._db.current_user_id()  # every row has an owner (the logged-in user; the local user in the CLI)
        with self._db.session() as session:
            record = SavedRecord(user_id=user_id, kind=args.kind, title=args.title, content=args.content)
            session.add(record)
            session.flush()  # sends the INSERT now, so the database assigns record.id
            return record.id


class QueryInput(BaseModel):
    record_id: int | None = Field(
        default=None, ge=1, description="Get ONE record with its full content, by id."
    )
    keyword: str | None = Field(
        default=None, max_length=100, description="Find records whose title or content contains this text."
    )
    kind: RecordKind | None = Field(default=None, description="Only records of this kind.")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of records to list.")


class DatabaseQueryTool(AgentTool):
    name = "database_query"
    input_model = QueryInput

    def __init__(self, database: Database) -> None:
        self._db = database

    async def run(self, args: QueryInput) -> str:  # type: ignore[override]
        text = await asyncio.to_thread(self._query, args)
        # Saved content may have come from web pages, so it is still untrusted.
        return wrap_untrusted(text, source="database/saved_records")

    def _query(self, args: QueryInput) -> str:
        user_id = self._db.current_user_id()
        with self._db.session() as session:
            if args.record_id is not None:
                record = session.get(SavedRecord, args.record_id)
                if record is None or record.user_id != user_id:  # never read another user's rows
                    raise ToolError(f"No saved record with id {args.record_id}.")
                return f"#{record.id} [{record.kind}] {record.title} ({record.created_at:%Y-%m-%d})\n\n{record.content}"

            query = (
                select(SavedRecord)
                .where(SavedRecord.user_id == user_id)
                .order_by(SavedRecord.created_at.desc(), SavedRecord.id.desc())
            )
            if args.kind:
                query = query.where(SavedRecord.kind == args.kind)
            if args.keyword:
                keyword = args.keyword.lower()
                # contains(..., autoescape=True) treats % and _ as normal characters,
                # so a keyword like "100%" can't act as a wildcard.
                query = query.where(
                    or_(
                        func.lower(SavedRecord.title).contains(keyword, autoescape=True),
                        func.lower(SavedRecord.content).contains(keyword, autoescape=True),
                    )
                )
            records = session.scalars(query.limit(args.limit)).all()

        if not records:
            return "No matching saved records."
        lines = [f"{len(records)} record(s) (use record_id to read one in full):"]
        for r in records:
            preview = " ".join(r.content.split())[:PREVIEW_CHARS]
            lines.append(f"#{r.id} [{r.kind}] {r.title} ({r.created_at:%Y-%m-%d})\n   {preview}")
        return "\n".join(lines)
