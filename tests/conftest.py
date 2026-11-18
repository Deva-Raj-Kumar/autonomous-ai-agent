"""Shared pytest fixtures. pytest loads this file automatically before running tests."""

import os
import tempfile

# ---------------------------------------------------------------------------
# TEST ISOLATION. This block runs when pytest loads conftest.py, BEFORE any test module
# imports the app. Real OS environment variables override .env, so the app (and its
# cached settings) can never reach your real MySQL database or your real data/ folder.
# Without this, tests that start the app would connect to MySQL from .env.
# ---------------------------------------------------------------------------
_TEST_DATA = tempfile.mkdtemp(prefix="agent_tests_")
os.environ.update(
    {
        "DATABASE_URL": "sqlite://",  # in-memory SQLite: created fresh, gone after the run
        "CHECKPOINT_DB_PATH": os.path.join(_TEST_DATA, "checkpoints.db"),
        "CHROMA_DIR": os.path.join(_TEST_DATA, "chroma"),
        "DOCUMENTS_DIR": os.path.join(_TEST_DATA, "documents"),
        "EMAIL_OUTBOX_DIR": os.path.join(_TEST_DATA, "outbox"),
        "ACCESS_TOKEN_MINUTES": "15",
    }
)

from unittest.mock import create_autospec  # noqa: E402  (imports after the isolation block)

import pytest  # noqa: E402

from app.llm.service import LLMService  # noqa: E402

# Environment variables that could leak from your real shell or .env into tests.
_ENV_VARS = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "LLM_PROVIDER",
    "ENVIRONMENT",
    "DEBUG",
    "LOG_LEVEL",
    "SEARCH_PROVIDER",
    "TAVILY_API_KEY",
    "ACCESS_TOKEN_MINUTES",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
)
# Note: DATABASE_URL / DOCUMENTS_DIR are NOT removed per test any more: the isolation
# block above points them at throwaway locations for the whole test session.


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test with a clean environment, so results don't depend on your machine.

    autouse=True applies this fixture to every test automatically.
    monkeypatch undoes all changes when each test finishes.
    """
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


_FOLDER_MARKERS = {"integration": "integration", "security": "security", "performance": "perf"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag tests by folder, so `pytest -m security` (or `-m "not perf"`) selects them."""
    for item in items:
        parts = item.path.parts
        for folder, marker in _FOLDER_MARKERS.items():
            if folder in parts and "tests" in parts:
                item.add_marker(marker)


@pytest.fixture(autouse=True)
def logged_in_as_local_user(request: pytest.FixtureRequest):
    """API tests that are NOT about authentication run as the local user (an admin), by
    replacing get_current_user. Everything after it still runs for real: require_user
    binds the user, and the stores scope data to them.
    Tests marked @pytest.mark.real_auth get no override and must send real tokens."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from fastapi import HTTPException, Request

    from app.api.auth import get_current_user
    from app.auth.schemas import AuthUser
    from app.main import app

    def local_admin(http_request: Request) -> AuthUser:
        database = http_request.app.state.database
        if database is None:
            raise HTTPException(503, detail="Accounts need a working database (check DATABASE_URL).")
        return AuthUser(id=database.default_user_id(), username="local", email="local@localhost", is_admin=True)

    app.dependency_overrides[get_current_user] = local_admin
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def close_databases(monkeypatch: pytest.MonkeyPatch):
    """Close every Database a test creates. Unclosed SQLite connections leak file
    handles and show up as 'ResourceWarning: unclosed database' (and on Windows they
    keep temp files locked). One fixture here beats remembering dispose() in 30 tests."""
    from app.database.connection import Database

    created: list[Database] = []
    original_init = Database.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(Database, "__init__", tracking_init)
    yield
    for database in created:
        database.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Run `@pytest.mark.anyio` async tests on asyncio (the plugin ships with anyio)."""
    return "asyncio"


@pytest.fixture
def mock_llm() -> LLMService:
    """A mock LLMService built with create_autospec.

    create_autospec copies the REAL class's methods and signatures:
      - async methods (chat, generate, structured, ...) become AsyncMocks
      - calling with wrong arguments raises TypeError, like the real method would
      - misspelled methods raise AttributeError instead of silently "working"
    Set behavior per test, e.g.  mock_llm.chat.return_value = "Hello!"
    """
    return create_autospec(LLMService, instance=True)
