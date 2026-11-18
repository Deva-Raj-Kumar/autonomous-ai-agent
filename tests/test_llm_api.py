"""API tests for the /llm endpoints, with LLMService replaced by a create_autospec mock."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_llm_service
from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.llm.example_tools import EXAMPLE_TOOLS
from app.llm.schemas import GoalAnalysis, ToolCallRecord, ToolRunResult
from app.main import app


@pytest.fixture
def client(mock_llm) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, google_api_key="k")
    app.dependency_overrides[get_llm_service] = lambda: mock_llm  # every request gets the mock
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_chat_endpoint(client: TestClient, mock_llm) -> None:
    mock_llm.chat.return_value = "RAG = retrieve, then generate."

    response = client.post("/llm/chat", json={"message": "What is RAG?"})

    assert response.status_code == 200
    assert response.json()["reply"] == "RAG = retrieve, then generate."
    mock_llm.chat.assert_awaited_once_with("What is RAG?")


def test_chat_rejects_empty_message(client: TestClient, mock_llm) -> None:
    response = client.post("/llm/chat", json={"message": ""})

    assert response.status_code == 422  # Pydantic validation error
    mock_llm.chat.assert_not_awaited()  # rejected before reaching the LLM


def test_chat_returns_502_when_llm_fails(client: TestClient, mock_llm) -> None:
    mock_llm.chat.side_effect = LLMError("provider down")

    response = client.post("/llm/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert "provider down" in response.json()["detail"]


def test_analyze_goal_endpoint(client: TestClient, mock_llm) -> None:
    mock_llm.analyze_goal.return_value = GoalAnalysis(
        summary="Find jobs",
        category="research",
        deliverables=["report"],
        required_capabilities=["web_search"],
        is_clear=True,
    )

    response = client.post("/llm/analyze-goal", json={"goal": "Find AI jobs in Hyderabad"})

    assert response.status_code == 200
    assert response.json()["category"] == "research"


def test_tools_demo_endpoint(client: TestClient, mock_llm) -> None:
    mock_llm.run_with_tools.return_value = ToolRunResult(
        answer="2 + 3 = 5",
        tool_calls=[
            ToolCallRecord(tool_name="add_numbers", arguments={"a": 2, "b": 3}, output="5", success=True)
        ],
        rounds=2,
    )

    response = client.post("/llm/tools-demo", json={"message": "add 2 and 3"})

    body = response.json()
    assert body["answer"] == "2 + 3 = 5"
    assert body["tool_calls"][0]["tool_name"] == "add_numbers"
    mock_llm.run_with_tools.assert_awaited_once_with("add 2 and 3", EXAMPLE_TOOLS)


def test_returns_503_without_api_key() -> None:
    # Only override settings (no key), so the REAL get_llm_service runs and refuses.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        with TestClient(app) as client:
            response = client.post("/llm/chat", json={"message": "hi"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "No API key" in response.json()["detail"]
