"""Pydantic models that define the exact shape of API requests and responses.

FastAPI uses these to validate data, serialize JSON, and generate the /docs page.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.memory.schemas import MemoryCategory
from app.timeutils import UTCDateTime


class HealthResponse(BaseModel):
    """Response body of GET /health."""

    status: Literal["ok"] = "ok"
    app_name: str
    version: str
    environment: str
    llm_provider: str
    llm_model: str
    llm_api_key_configured: bool = Field(
        description="Whether the selected provider's API key is set. The key itself is never returned."
    )


# max_length limits are a cheap safety measure: they cap cost and stop
# someone from pasting a huge prompt into the API.
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000, examples=["Explain RAG in 3 sentences."])


class ChatResponse(BaseModel):
    reply: str
    model: str


class GoalRequest(BaseModel):
    goal: str = Field(
        min_length=3,
        max_length=2_000,
        examples=[
            "Research the top 10 AI Engineer fresher jobs in Bengaluru and Hyderabad, "
            "compare their required skills, generate a report, and save it in the database."
        ],
    )


class ToolDemoRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=2_000,
        examples=["What time is it in Tokyo, and what is 23.5 multiplied by 19?"],
    )


class ToolInfo(BaseModel):
    name: str
    description: str
    requires_approval: bool
    available: bool = Field(description="False if the tool is planned but not implemented/enabled yet.")
    input_schema: dict[str, Any] | None


class ToolExecuteRequest(BaseModel):
    arguments: dict[str, Any] = Field(
        default_factory=dict, examples=[{"expression": "(45000 + 52000) / 2"}]
    )


class MemoryChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000, examples=["Hi, I'm learning LangGraph."])
    session_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Omit to start a new session; reuse the returned id to continue.",
    )


class MessageOut(BaseModel):
    role: str
    content: str
    created_at: UTCDateTime


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=300, examples=["User prefers remote jobs."])
    category: MemoryCategory = "other"
    importance: int = Field(default=3, ge=1, le=5)


class MemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=300)
    category: MemoryCategory | None = None
    importance: int | None = Field(default=None, ge=1, le=5)


class IngestReportOut(BaseModel):
    source: str
    status: Literal["ingested", "unchanged", "skipped", "failed"]
    chunks: int = 0
    detail: str = ""


class DocumentOut(BaseModel):
    source: str
    chunks: int
    pages: list[int] = Field(default_factory=list)
    ingested_at: str = ""


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500, examples=["What skills does the AI engineer job need?"])
    k: int = Field(default=4, ge=1, le=20)


class KnowledgeAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1_000, examples=["What is the salary range?"])
    k: int | None = Field(default=None, ge=1, le=20)


class AgentRunRequest(BaseModel):
    goal: str = Field(
        min_length=3,
        max_length=2_000,
        examples=["Compare AI engineer fresher jobs in Bengaluru and Hyderabad and write a short report."],
    )


class RunSummary(BaseModel):
    run_id: str
    goal: str
    status: str
    steps_used: int
    created_at: str
    running: bool
    resumable: bool


class RunStarted(BaseModel):
    run_id: str
    status: str = "started"
    links: dict[str, str] = Field(default_factory=dict)

