"""API tests for /tools.

UNIT tests: the ToolRegistry is a create_autospec mock, so we test only the HTTP layer
(routing, status codes, what gets passed to the registry).
INTEGRATION tests at the end: a real registry (temp folder, in-memory DB).
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_tool_registry
from app.config import Settings
from app.database.connection import Database
from app.main import app
from app.tools.base import ToolResult, ToolStatus
from app.tools.registry import ToolRegistry, build_default_registry


@pytest.fixture
def mock_registry() -> ToolRegistry:
    registry = create_autospec(ToolRegistry, instance=True)
    registry.is_available.return_value = True
    return registry


@pytest.fixture
def client(mock_registry) -> Iterator[TestClient]:
    app.dependency_overrides[get_tool_registry] = lambda: mock_registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------- unit tests
def test_list_tools_returns_registry_description(client: TestClient, mock_registry) -> None:
    mock_registry.describe.return_value = [
        {"name": "calculator", "description": "math", "requires_approval": False,
         "available": True, "input_schema": {"type": "object"}},
    ]

    tools = client.get("/tools").json()

    assert tools[0]["name"] == "calculator"
    mock_registry.describe.assert_called_once()


def test_execute_passes_arguments_to_registry(client: TestClient, mock_registry) -> None:
    mock_registry.execute.return_value = ToolResult(
        tool_name="calculator", status=ToolStatus.SUCCESS, output="6*7 = 42"
    )

    response = client.post("/tools/calculator/execute", json={"arguments": {"expression": "6*7"}})

    assert response.json()["output"] == "6*7 = 42"
    # The API never approves sensitive tools: execute() is called WITHOUT approved=True.
    mock_registry.execute.assert_awaited_once_with("calculator", {"expression": "6*7"})


def test_needs_approval_result_is_returned_as_is(client: TestClient, mock_registry) -> None:
    mock_registry.execute.return_value = ToolResult(
        tool_name="python_exec", status=ToolStatus.NEEDS_APPROVAL, error="Human approval required."
    )

    response = client.post("/tools/python_exec/execute", json={"arguments": {"code": "print(1)"}})

    assert response.status_code == 200 and response.json()["status"] == "needs_approval"


def test_unavailable_tool_is_404(client: TestClient, mock_registry) -> None:
    mock_registry.is_available.return_value = False

    response = client.post("/tools/send_email/execute", json={})

    assert response.status_code == 404
    mock_registry.execute.assert_not_awaited()


# -------------------------------------------------------- integration tests
@pytest.fixture
def real_client(tmp_path: Path) -> Iterator[TestClient]:
    (tmp_path / "hello.txt").write_text("hello from a test file", encoding="utf-8")
    database = Database("sqlite://")
    database.create_tables()
    registry = build_default_registry(Settings(_env_file=None, documents_dir=tmp_path), database)
    app.dependency_overrides[get_tool_registry] = lambda: registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_integration_real_tools(real_client: TestClient) -> None:
    calc = real_client.post("/tools/calculator/execute", json={"arguments": {"expression": "6*7"}})
    read = real_client.post("/tools/read_file/execute", json={"arguments": {"path": "hello.txt"}})
    bad = real_client.post("/tools/calculator/execute", json={"arguments": {}})

    assert calc.json()["output"] == "6*7 = 42"
    assert "hello from a test file" in read.json()["output"]
    assert bad.json()["status"] == "error" and "expression" in bad.json()["error"]


def test_integration_catalog_listing(real_client: TestClient) -> None:
    tools = {t["name"]: t for t in real_client.get("/tools").json()}

    assert tools["calculator"]["available"] is True
    assert tools["python_exec"]["requires_approval"] is True
    # send_email exists since Phase 10 (outbox mode) and always needs approval.
    assert tools["send_email"]["available"] is True and tools["send_email"]["requires_approval"] is True
    assert tools["search_knowledge_base"]["available"] is False  # no knowledge base in this test
