"""Application entry point.

Run the server with:
    uvicorn app.main:app --reload

"app.main:app" means: in the module app/main.py, use the variable named `app`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app import __version__
from app.agent.workflow import AgentWorkflow
from app.api.auth import auth_router, require_user
from app.api.email_routes import email_router
from app.api.middleware import install_middleware
from app.api.routes import (
    agent_router,
    approvals_router,
    knowledge_router,
    llm_router,
    memory_router,
    router,
    tools_router,
)
from app.auth.security import TokenConfig, resolve_jwt_secret
from app.auth.service import AuthService
from app.auth.throttle import LoginThrottle
from app.config import DATA_DIR, get_settings
from app.database.connection import open_database
from app.database.crud import RunRepository
from app.llm.service import LLMService
from app.logging_config import setup_logging
from app.memory.long_term import LongTermMemory
from app.memory.vector_store import MemoryVectorIndex, build_vector_store
from app.rag.retrieval import build_knowledge_base
from app.safety.approval import ApprovalStore
from app.tools.registry import build_default_registry

logger = logging.getLogger(__name__)  # __name__ == "app.main", shown in every log line


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code before `yield` runs once at startup; code after it runs once at shutdown.

    Shared, long-lived objects (database, tool registry) are created ONCE here and
    stored on app.state, instead of being rebuilt on every request.
    Phase 8 adds the LangGraph checkpointer here.
    """
    settings = get_settings()
    DATA_DIR.mkdir(exist_ok=True)  # folder for the SQLite DB, ChromaDB, reports
    settings.documents_dir.mkdir(parents=True, exist_ok=True)  # the only folder read_file can read

    database = open_database(settings.database_url, auto_migrate=settings.db_auto_migrate)
    app.state.database = database

    # Accounts (Phase 12). From here on, data access without a logged-in user raises.
    app.state.auth_service = None
    app.state.login_throttle = LoginThrottle(settings.login_max_failures, settings.login_window_minutes * 60)
    if database is not None:
        database.require_login = True
        secret = settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else None
        app.state.auth_service = AuthService(database, TokenConfig(
            secret=resolve_jwt_secret(secret), algorithm=settings.jwt_algorithm,
            access_minutes=settings.access_token_minutes, refresh_days=settings.refresh_token_days,
        ))
    else:
        logger.warning("Accounts disabled (no database): every endpoint except /health returns 503.")

    # RAG + semantic memory share one vector store. If it can't be created (e.g.
    # EMBEDDING_PROVIDER=gemini without a key), the app runs without those features.
    app.state.vector_store = app.state.knowledge_base = app.state.memory_index = None
    try:
        store = build_vector_store(settings)
        app.state.vector_store = store
        app.state.knowledge_base = build_knowledge_base(settings, store)
        if settings.memory_semantic_search:
            app.state.memory_index = MemoryVectorIndex(store)
        logger.info("Vector store ready (embedder: %s)", store.embedder.name)
    except Exception as exc:
        logger.warning("RAG disabled: could not create the vector store (%s).", exc)

    # The reasoning tools (llm_analysis, generate_report) need an LLM. A factory is
    # passed instead of a model, so startup works even before an API key is configured.
    llm_factory = (lambda: LLMService.from_settings(settings)) if settings.llm_api_key_configured else None
    app.state.tool_registry = build_default_registry(
        settings, database, app.state.knowledge_base, llm_factory=llm_factory
    )

    # LangGraph workflow with persistent checkpoints. The checkpointer is an async
    # context manager (it owns a SQLite connection), so it is entered on an exit stack
    # and closed at shutdown.
    resources = AsyncExitStack()
    app.state.workflow = None
    # Approval audit trail (needs the main database; without it, approvals still work
    # through the checkpoints but are not recorded in a table).
    app.state.approval_store = ApprovalStore(database) if database is not None else None
    app.state.run_repository = RunRepository(database) if database is not None else None
    if llm_factory is not None:
        settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = await resources.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path))
        )
        app.state.workflow = AgentWorkflow(
            llm_factory=llm_factory, registry=app.state.tool_registry,
            settings=settings, checkpointer=checkpointer, approval_store=app.state.approval_store,
            run_repository=app.state.run_repository,
        )

    # Embed memories created before Phase 6. Loading the embedding model can take
    # seconds, so it runs as a BACKGROUND task: the server starts answering immediately.
    sync_task = None
    if database is not None and app.state.memory_index is not None:
        sync_task = asyncio.create_task(_sync_memory_index(database, app.state.memory_index))
    available = [t["name"] for t in app.state.tool_registry.describe() if t["available"]]
    logger.info("Tools available: %s", ", ".join(available))
    logger.info(
        "Starting %s v%s | env=%s | provider=%s | model=%s",
        settings.app_name,
        __version__,
        settings.environment,
        settings.llm_provider,
        settings.active_model,
    )
    if not settings.llm_api_key_configured:
        # A warning, not a crash: Phase 1 runs fine without a key.
        logger.warning(
            "No API key found for provider '%s'. Add it to .env before Phase 2.",
            settings.llm_provider,
        )
    yield
    if app.state.workflow is not None:
        await app.state.workflow.shutdown()  # cancel workers; checkpoints stay resumable
    await resources.aclose()
    if sync_task is not None and not sync_task.done():
        sync_task.cancel()  # don't leave background work running after shutdown
    if database is not None:
        database.dispose()
    logger.info("Shutting down %s", settings.app_name)


async def _sync_memory_index(database, index: MemoryVectorIndex) -> None:
    try:
        added = await LongTermMemory(database, index).sync_index()
        if added:
            logger.info("Semantic memory index: embedded %d existing memories", added)
    except Exception as exc:  # background task: log, never crash the app
        logger.warning("Semantic memory index sync failed: %s", exc)


def create_app() -> FastAPI:
    """Application factory: builds and returns a configured FastAPI app.

    A factory function (instead of building the app at import time with no
    function) makes it easy to create fresh, independent apps in tests.
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="A personal autonomous AI agent: plans, uses tools, remembers, and reports.",
        debug=settings.debug,
        lifespan=lifespan,
    )
    # Browsers block cross-origin calls unless the API allows that origin (CORS).
    # Only listed origins; Authorization header allowed; no cookies needed (bearer tokens).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    install_middleware(app)

    # Public: / and /health, plus the /auth endpoints (they handle their own checks).
    app.include_router(router)
    app.include_router(auth_router)
    # Everything else requires a logged-in user. Attached HERE, per router, so a new
    # endpoint is protected by default instead of relying on each one to remember.
    login_required = [Depends(require_user)]
    for protected in (llm_router, agent_router, tools_router, memory_router, knowledge_router, approvals_router, email_router):
        app.include_router(protected, dependencies=login_required)
    return app


app = create_app()
