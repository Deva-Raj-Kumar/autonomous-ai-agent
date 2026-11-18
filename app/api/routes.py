"""HTTP routes (endpoints).

An APIRouter groups related endpoints. main.py "includes" these routers into the app,
and attaches the login requirement (require_user) to every router except `router`
(/ and /health), so a new endpoint is protected by default.
"""

import asyncio
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse

from app import __version__
from app.agent.planner import Planner
from app.agent.schemas import PlanningResult
from app.agent.workflow import AgentWorkflow, ApprovalDecision, RunView
from app.api.auth import require_admin, require_user
from app.api.schemas import (
    AgentRunRequest,
    ChatRequest,
    ChatResponse,
    DocumentOut,
    GoalRequest,
    HealthResponse,
    IngestReportOut,
    KnowledgeAskRequest,
    KnowledgeSearchRequest,
    MemoryChatRequest,
    MemoryCreate,
    MemoryUpdate,
    MessageOut,
    RunStarted,
    RunSummary,
    ToolDemoRequest,
    ToolExecuteRequest,
    ToolInfo,
)
from app.auth.schemas import AuthUser
from app.config import DATA_DIR, Settings, get_settings
from app.database.connection import Database
from app.database.crud import RunHistory, RunRepository
from app.llm.client import LLMConfigurationError, LLMError
from app.llm.example_tools import EXAMPLE_TOOLS
from app.llm.schemas import GoalAnalysis, ToolRunResult
from app.llm.service import LLMService
from app.memory.long_term import LongTermMemory, MemoryRejected
from app.memory.manager import MemoryManager
from app.memory.schemas import ChatTurn, MemoryRecord, ScoredMemory
from app.memory.short_term import ConversationStore
from app.memory.vector_store import MemoryVectorIndex
from app.rag.ingestion import ALLOWED_EXTENSIONS
from app.rag.retrieval import KnowledgeBase, RAGAnswer, RetrievedChunk
from app.safety.approval import ApprovalOut, ApprovalStore
from app.safety.secrets import redact_secrets
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry

router = APIRouter(tags=["system"])
llm_router = APIRouter(prefix="/llm", tags=["llm"])
agent_router = APIRouter(prefix="/agent", tags=["agent"])
tools_router = APIRouter(prefix="/tools", tags=["tools"])
memory_router = APIRouter(tags=["memory"])
knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge (RAG)"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])

SESSION_ID = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Chat session id")
MEMORY_ID = Path(ge=1, le=9223372036854775807, description="Memory id")

# Annotated[Settings, Depends(get_settings)] tells FastAPI: "before running this
# endpoint, call get_settings() and pass the result in as `settings`".
# This is dependency injection: tests can replace get_settings with fake settings.
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_llm_service(settings: SettingsDep) -> LLMService:
    """Dependency that builds the LLM service, or returns 503 if it isn't configured."""
    try:
        return LLMService.from_settings(settings)
    except LLMConfigurationError as exc:
        # 503 Service Unavailable: the server works, but this feature isn't set up.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


LLMServiceDep = Annotated[LLMService, Depends(get_llm_service)]


def get_tool_registry(request: Request) -> ToolRegistry:
    """The registry is built once at startup (see lifespan in main.py)."""
    return request.app.state.tool_registry


ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]


def get_planner(llm: LLMServiceDep, settings: SettingsDep, registry: ToolRegistryDep) -> Planner:
    """Dependency that builds a Planner that plans ONLY with tools available right now."""
    return Planner.from_settings(llm, settings, tools=registry.available_specs())


PlannerDep = Annotated[Planner, Depends(get_planner)]


def _bad_gateway(exc: LLMError) -> HTTPException:
    """502 Bad Gateway: an upstream service (the LLM provider) failed.
    The message is redacted: provider errors can echo request details."""
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=redact_secrets(str(exc)))


# ------------------------------------------------------------------ system
@router.get("/")
async def root() -> dict[str, str]:
    """Small landing response that points to the interactive docs."""
    return {"message": "Vision AI API is running", "docs": "/docs"}


AdminOnly = [Depends(require_admin)]
CurrentUserDep = Annotated[AuthUser, Depends(require_user)]  # cached: runs once per request


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Liveness check. Used by you, by tests, and later by Docker/cloud health checks."""
    return HealthResponse(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        llm_model=settings.active_model,
        llm_api_key_configured=settings.llm_api_key_configured,
    )


@router.get("/health/ready")
async def readiness(request: Request) -> Response:
    """Readiness: can this instance serve real traffic? (/health only says "the process
    is alive".) Load balancers send traffic only to instances that answer 200 here."""
    database = request.app.state.database
    db_ok = database is not None and await asyncio.to_thread(database.ping)
    body = {"status": "ready" if db_ok else "not_ready", "database": db_ok,
            "agent": getattr(request.app.state, "workflow", None) is not None}
    return JSONResponse(body, status_code=200 if db_ok else 503)


# --------------------------------------------------------------------- LLM
@llm_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, llm: LLMServiceDep, settings: SettingsDep) -> ChatResponse:
    """Plain chat with the configured model."""
    try:
        reply = await llm.chat(request.message)
    except LLMError as exc:
        raise _bad_gateway(exc) from exc
    return ChatResponse(reply=reply, model=settings.active_model)


@llm_router.post("/analyze-goal", response_model=GoalAnalysis)
async def analyze_goal(request: GoalRequest, llm: LLMServiceDep) -> GoalAnalysis:
    """Structured outputs demo: turn a goal into a validated GoalAnalysis object."""
    try:
        return await llm.analyze_goal(request.goal)
    except LLMError as exc:
        raise _bad_gateway(exc) from exc


@llm_router.post("/tools-demo", response_model=ToolRunResult)
async def tools_demo(request: ToolDemoRequest, llm: LLMServiceDep) -> ToolRunResult:
    """Function-calling demo with three safe example tools (time, add, multiply)."""
    try:
        return await llm.run_with_tools(request.message, EXAMPLE_TOOLS)
    except LLMError as exc:
        raise _bad_gateway(exc) from exc


# ------------------------------------------------------------------- agent
@agent_router.post("/plan", response_model=PlanningResult)
async def create_plan(request: GoalRequest, planner: PlannerDep) -> PlanningResult:
    """Plan a goal: analysis, tasks, dependencies, execution order and parallel waves.

    Returns status "needs_clarification" with questions if the goal is too vague.
    Nothing is executed yet: execution arrives in Phase 7.
    """
    try:
        return await planner.create_plan(request.goal)
    except LLMError as exc:  # includes PlanningError
        raise _bad_gateway(exc) from exc


# ------------------------------------------------------------------- tools
@tools_router.get("", response_model=list[ToolInfo])
async def list_tools(registry: ToolRegistryDep) -> list[dict]:
    """Every tool in the catalog, whether it's available, and its input schema."""
    return registry.describe()


@tools_router.post("/{name}/execute", response_model=ToolResult)
async def execute_tool(name: str, request: ToolExecuteRequest, registry: ToolRegistryDep) -> ToolResult:
    """Run one tool directly (useful for testing tools without the LLM).

    Tools that need approval return status "needs_approval" here: approvals happen
    inside agent runs (POST /agent/runs/{run_id}/approval).
    """
    if not registry.is_available(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Tool '{name}' is not available.")
    return await registry.execute(name, request.arguments)


# ------------------------------------------------------------------ memory
def get_database(request: Request) -> Database:
    """The database opened at startup, or 503 if it couldn't be opened."""
    database = request.app.state.database
    if database is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory needs a working database. Fix DATABASE_URL in .env "
            "(or remove it to use the default SQLite file).",
        )
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]


def get_memory_index(request: Request) -> MemoryVectorIndex | None:
    """Semantic memory index from startup; None means keyword-only memory search."""
    return getattr(request.app.state, "memory_index", None)


MemoryIndexDep = Annotated[MemoryVectorIndex | None, Depends(get_memory_index)]


def get_long_term_memory(database: DatabaseDep, index: MemoryIndexDep) -> LongTermMemory:
    return LongTermMemory(database, index)


def get_memory_manager(
    llm: LLMServiceDep, database: DatabaseDep, settings: SettingsDep, index: MemoryIndexDep
) -> MemoryManager:
    return MemoryManager(llm, ConversationStore(database), LongTermMemory(database, index), settings)


LongTermDep = Annotated[LongTermMemory, Depends(get_long_term_memory)]
MemoryManagerDep = Annotated[MemoryManager, Depends(get_memory_manager)]


@memory_router.post("/chat", response_model=ChatTurn)
async def chat_with_memory(request: MemoryChatRequest, manager: MemoryManagerDep) -> ChatTurn:
    """Chat with conversation memory + long-term memory. Omit session_id to start a
    new session; send the returned session_id back to continue it."""
    try:
        return await manager.chat(request.message, request.session_id)
    except LLMError as exc:
        raise _bad_gateway(exc) from exc


@memory_router.get("/chat/{session_id}/history", response_model=list[MessageOut])
async def chat_history(
    manager: MemoryManagerDep, session_id: Annotated[str, SESSION_ID]
) -> list[MessageOut]:
    messages = await manager.conversations.history(session_id)
    return [MessageOut(role=m.role, content=m.content, created_at=m.created_at) for m in messages]


@memory_router.delete("/chat/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(manager: MemoryManagerDep, session_id: Annotated[str, SESSION_ID]) -> Response:
    if not await manager.conversations.delete_session(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@memory_router.get("/memories", response_model=list[MemoryRecord])
async def list_memories(
    memory: LongTermDep,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MemoryRecord]:
    """Everything the agent remembers about you. You can always see and delete it."""
    return await memory.list_memories(category=category, limit=limit)


@memory_router.get("/memories/search", response_model=list[ScoredMemory])
async def search_memories(
    memory: LongTermDep,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[ScoredMemory]:
    """See exactly which memories a message would recall, with their scores."""
    return await memory.search(q, limit=limit, mark_accessed=False)


@memory_router.post("/memories", response_model=MemoryRecord, status_code=status.HTTP_201_CREATED)
async def create_memory(body: MemoryCreate, memory: LongTermDep) -> MemoryRecord:
    try:
        record, _created = await memory.add(
            body.content, category=body.category, importance=body.importance, source="manual"
        )
    except MemoryRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return record


@memory_router.put("/memories/{memory_id}", response_model=MemoryRecord)
async def update_memory(
    memory_id: Annotated[int, MEMORY_ID], body: MemoryUpdate, memory: LongTermDep
) -> MemoryRecord:
    try:
        record = await memory.update(
            memory_id, body.content, category=body.category, importance=body.importance
        )
    except MemoryRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return record


@memory_router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: Annotated[int, MEMORY_ID], memory: LongTermDep) -> Response:
    if not await memory.delete(memory_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- knowledge (RAG)
UPLOAD_CHUNK_BYTES = 1024 * 1024


def get_knowledge_base(request: Request) -> KnowledgeBase:
    kb = getattr(request.app.state, "knowledge_base", None)
    if kb is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge base unavailable: the vector store could not be created (see server log).",
        )
    return kb


KnowledgeBaseDep = Annotated[KnowledgeBase, Depends(get_knowledge_base)]


def safe_upload_name(filename: str | None) -> str:
    """Reduce an uploaded file name to a bare, allowed file name, or raise HTTP 400/415.

    Uploaded files are untrusted: "../../app/main.py" or "C:\\Windows\\x.txt" become just
    the final name, hidden files are refused, and the extension must be allow-listed.
    """
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name.startswith("."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid file name.")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Allowed types: {allowed}.")
    return name


# The knowledge base is SHARED by all users, so changing it is admin-only.
@knowledge_router.post("/ingest", response_model=list[IngestReportOut], dependencies=AdminOnly)
async def ingest_documents(kb: KnowledgeBaseDep) -> list[IngestReportOut]:
    """Ingest every file in the documents folder. Unchanged files are skipped."""
    return [IngestReportOut(**vars(r)) for r in await kb.ingestor.ingest_all()]


@knowledge_router.post(
    "/upload", response_model=IngestReportOut, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly
)
async def upload_document(file: UploadFile, kb: KnowledgeBaseDep, settings: SettingsDep) -> IngestReportOut:
    """Upload a PDF/DOCX/TXT/MD file into the documents folder and ingest it.

    The size is checked WHILE reading, so a huge upload is rejected before it fills memory.
    """
    name = safe_upload_name(file.filename)
    max_bytes = int(settings.max_file_size_mb * 1024 * 1024)
    data = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="File is too large.")

    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    (settings.documents_dir / name).write_bytes(bytes(data))
    return IngestReportOut(**vars(await kb.ingestor.ingest_file(name)))


@knowledge_router.get("/documents", response_model=list[DocumentOut])
async def list_documents(kb: KnowledgeBaseDep) -> list[DocumentOut]:
    return [DocumentOut(**vars(d)) for d in await kb.ingestor.list_documents()]


@knowledge_router.delete("/documents/{source:path}", status_code=status.HTTP_204_NO_CONTENT, dependencies=AdminOnly)
async def delete_document(source: str, kb: KnowledgeBaseDep) -> Response:
    """Remove a document from the knowledge base (the file stays in the folder)."""
    if not await kb.ingestor.delete_document(source):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found in the knowledge base.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@knowledge_router.post("/search", response_model=list[RetrievedChunk])
async def search_knowledge(body: KnowledgeSearchRequest, kb: KnowledgeBaseDep) -> list[RetrievedChunk]:
    """Semantic search with reranking. Shows scores, which helps you tune retrieval."""
    return await kb.search(body.query, k=body.k)


@knowledge_router.post("/ask", response_model=RAGAnswer)
async def ask_knowledge(body: KnowledgeAskRequest, kb: KnowledgeBaseDep, llm: LLMServiceDep) -> RAGAnswer:
    """Answer a question from your documents, with numbered citations."""
    try:
        return await kb.answer(body.question, llm, k=body.k)
    except LLMError as exc:
        raise _bad_gateway(exc) from exc


# ------------------------------------------------- agent runs (LangGraph, Phase 8)
def get_workflow(request: Request) -> AgentWorkflow:
    workflow = getattr(request.app.state, "workflow", None)
    if workflow is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent workflow unavailable: configure an LLM API key in .env.",
        )
    return workflow


WorkflowDep = Annotated[AgentWorkflow, Depends(get_workflow)]


async def _existing_run(workflow: AgentWorkflow, run_id: str) -> RunView:
    """The run, if it exists AND belongs to the current user. Someone else's run gets
    the same 404 as a missing one: a 403 would confirm that the id exists."""
    view = await workflow.get(run_id) if await workflow.owns(run_id) else None
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return view


def _links(run_id: str) -> dict[str, str]:
    return {"self": f"/agent/runs/{run_id}", "approval": f"/agent/runs/{run_id}/approval"}


@agent_router.post("/run", response_model=RunView)
async def run_agent(body: AgentRunRequest, workflow: WorkflowDep) -> RunView:
    """Run a goal and WAIT for it to finish or pause (simple, but the request can take a
    minute). For long goals prefer POST /agent/runs, which returns immediately."""
    run_id = await workflow.start(body.goal)
    return await _existing_run(workflow, run_id)


@agent_router.post("/runs", response_model=RunStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_run(body: AgentRunRequest, workflow: WorkflowDep) -> RunStarted:
    """Start a run in the BACKGROUND. 202 Accepted = "received, working on it".
    Poll GET /agent/runs/{run_id} to follow progress."""
    run_id = await workflow.start_in_background(body.goal)
    return RunStarted(run_id=run_id, links=_links(run_id))


@agent_router.get("/runs", response_model=list[RunSummary])
async def list_runs(workflow: WorkflowDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[RunSummary]:
    """Recent runs, newest first. Stored as checkpoints, so they survive restarts."""
    return [
        RunSummary(
            run_id=v.run_id, goal=v.goal, status=v.status, steps_used=v.steps_used,
            created_at=v.created_at, running=v.running, resumable=v.resumable,
        )
        for v in await workflow.list_runs(limit)
    ]


@agent_router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str, workflow: WorkflowDep) -> RunView:
    """Full run state from the latest checkpoint: plan, records, approvals, report."""
    return await _existing_run(workflow, run_id)


@agent_router.post("/runs/{run_id}/approval", response_model=RunStarted, status_code=status.HTTP_202_ACCEPTED)
async def decide_approval(
    run_id: str, decision: ApprovalDecision, workflow: WorkflowDep, user: CurrentUserDep
) -> RunStarted:
    """Approve some waiting tasks (any waiting task NOT listed is rejected) and resume."""
    view = await _existing_run(workflow, run_id)
    if view.running or not view.pending_approvals:
        # 409 Conflict: the request is valid, but the run isn't in a state that accepts it.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This run is not waiting for approval.")
    unknown = set(decision.approved) - {t["id"] for t in view.pending_approvals}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Not waiting for approval: {sorted(unknown)}")
    # The audit trail records WHO approved, from the verified token: a decided_by
    # value sent by the client is always overwritten (never trust it).
    decided_by = f"user:{user.id}:{user.username}"
    workflow.approve_in_background(run_id, decision.model_copy(update={"decided_by": decided_by}))
    return RunStarted(run_id=run_id, status="resumed", links=_links(run_id))


@agent_router.post("/runs/{run_id}/continue", response_model=RunStarted, status_code=status.HTTP_202_ACCEPTED)
async def continue_run(run_id: str, workflow: WorkflowDep) -> RunStarted:
    """Resume a run that was interrupted mid-way (e.g. the server restarted), from its
    last checkpoint. Completed tasks are not repeated."""
    view = await _existing_run(workflow, run_id)
    if not view.resumable:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This run is finished, running, or waiting for approval.")
    workflow.continue_in_background(run_id)
    return RunStarted(run_id=run_id, status="resumed", links=_links(run_id))


# ------------------------------------------------------ approvals audit (Phase 10)
def get_approval_store(request: Request) -> ApprovalStore:
    store = getattr(request.app.state, "approval_store", None)
    if store is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approval records need a working database (check DATABASE_URL in .env).",
        )
    return store


ApprovalStoreDep = Annotated[ApprovalStore, Depends(get_approval_store)]


@approvals_router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    store: ApprovalStoreDep,
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(pending|approved|rejected)$")] = None,
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ApprovalOut]:
    """Audit trail of sensitive actions: what was proposed (exact arguments + SHA-256
    fingerprint), the decision, who made it and when. ?status=pending for the to-do list."""
    return await store.list_records(status=status_filter, run_id=run_id, limit=limit)


# --------------------------------------------------------- run history (Phase 11)
def get_run_repository(request: Request) -> RunRepository:
    repository = getattr(request.app.state, "run_repository", None)
    if repository is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run history needs a working database (check DATABASE_URL and run: alembic upgrade head).",
        )
    return repository


RunRepositoryDep = Annotated[RunRepository, Depends(get_run_repository)]


@agent_router.get("/runs/{run_id}/history", response_model=RunHistory)
async def run_history(run_id: str, repository: RunRepositoryDep) -> RunHistory:
    """Permanent history from the database: the plan's steps and EVERY tool call
    (inputs, output preview, status, timing, security flags)."""
    history = await repository.history(run_id)
    if history is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No history for this run.")
    return history


@agent_router.get("/reports")
async def list_reports() -> list[dict]:
    """List generated report files (Excel, CSV, Markdown) available for download."""
    results = []
    seen = set()
    for search_dir in (DATA_DIR, DATA_DIR / "reports"):
        if not search_dir.exists():
            continue
        for p in search_dir.iterdir():
            if p.is_file() and p.suffix.lower() in {".xlsx", ".csv", ".md"}:
                if p.name in seen:
                    continue
                seen.add(p.name)
                stat = p.stat()
                results.append({
                    "name": p.name,
                    "extension": p.suffix.lower().lstrip("."),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                })
    results.sort(key=lambda r: (r["extension"] not in {"xlsx", "csv"}, -r["modified_at"]))
    return results


@agent_router.get("/reports/{filename}/download")
async def download_report(filename: str):
    """Safely download a generated report or data file."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")

    file_path = None
    for candidate in (DATA_DIR / filename, DATA_DIR / "reports" / filename):
        if candidate.is_file():
            file_path = candidate
            break

    if not file_path or not file_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Report file '{filename}' not found.")

    media_types = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
    }
    media_type = media_types.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )

