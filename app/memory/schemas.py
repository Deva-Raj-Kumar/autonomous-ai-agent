"""Pydantic schemas for the memory system.

Same two-layer idea as the planner:
  - MemoryOperation / MemoryExtraction: what the LLM may PROPOSE.
  - MemoryRecord / MemoryChange: what our code actually stored, and what happened.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.timeutils import UTCDateTime

MemoryCategory = Literal["profile", "preference", "goal", "skill", "project", "other"]


class MemoryRecord(BaseModel):
    """A stored long-term memory, as returned by the API and used in prompts."""

    # from_attributes=True lets Pydantic read a SQLAlchemy object: MemoryRecord.model_validate(row)
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    category: str
    importance: int
    source: str
    # Nullable in the database: rows written by OTHER tools into your memories table
    # may leave them empty, and one such row must not break the whole list (a 500).
    created_at: UTCDateTime | None = None
    updated_at: UTCDateTime | None = None
    access_count: int = 0

    @field_validator("content", "category", "source", mode="before")
    @classmethod
    def _fill_missing_text(cls, value, info):
        if value is None:
            return {"content": "", "category": "other", "source": "unknown"}[info.field_name]
        return value


class ScoredMemory(BaseModel):
    """A memory plus why it was retrieved (useful for debugging retrieval quality)."""

    memory: MemoryRecord
    score: float
    relevance: float
    recency: float


# ------------------------------------------------------------- LLM-facing
class MemoryOperation(BaseModel):
    """One change the LLM proposes to long-term memory."""

    action: Literal["add", "update", "delete"] = Field(
        description="add = new fact; update = replace an existing memory's content; "
        "delete = remove an existing memory (only if the user asks to forget it or it is now false)."
    )
    memory_id: int | None = Field(
        default=None,
        description="Required for update and delete: the id of one of the EXISTING memories shown.",
    )
    content: str = Field(
        default="",
        description="The fact as one short third-person sentence, e.g. 'User lives in Hyderabad.' "
        "Empty for delete.",
    )
    category: MemoryCategory = Field(default="other", description="Type of fact.")
    importance: int = Field(
        default=3, description="1 = trivia, 3 = useful, 5 = core identity or long-term goal."
    )


class MemoryExtraction(BaseModel):
    """The LLM's full answer. Usually EMPTY: most messages contain nothing worth remembering."""

    operations: list[MemoryOperation] = Field(default_factory=list)


# ------------------------------------------------------------------ results
class MemoryChange(BaseModel):
    """What happened to one proposed operation after validation."""

    action: Literal["add", "update", "delete"]
    memory_id: int | None
    content: str
    applied: bool
    reason: str = ""  # why it was skipped, or "duplicate" etc.


class ChatTurn(BaseModel):
    """Result of one chat turn with memory."""

    session_id: str
    reply: str
    memories_used: list[MemoryRecord]
    memory_changes: list[MemoryChange]
    summarized: bool = Field(description="True if older messages were folded into the summary.")
