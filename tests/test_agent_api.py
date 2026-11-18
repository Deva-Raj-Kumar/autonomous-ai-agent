"""API tests for /agent/plan, with LLMService replaced by a create_autospec mock.

The REAL Planner runs (validation, graph ordering); only the LLM is mocked.
"""

from collections.abc import Iterator
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_llm_service, get_tool_registry
from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.main import app
from app.tools.catalog import TOOL_CATALOG
from app.tools.registry import ToolRegistry
from tests.test_planner import GOOD_DRAFT, make_analysis


@pytest.fixture
def client(mock_llm) -> Iterator[TestClient]:
    # The planner only plans with AVAILABLE tools, so the test states which exist:
    # here, every tool in the catalog.
    registry = create_autospec(ToolRegistry, instance=True)
    registry.available_specs.return_value = list(TOOL_CATALOG)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, google_api_key="k")
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    app.dependency_overrides[get_tool_registry] = lambda: registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_plan_endpoint_returns_plan(client: TestClient, mock_llm) -> None:
    mock_llm.analyze_goal.return_value = make_analysis()
    mock_llm.structured.return_value = GOOD_DRAFT

    response = client.post("/agent/plan", json={"goal": "Compare AI jobs in two cities"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "planned"
    assert len(body["plan"]["tasks"]) == 5
    assert body["plan"]["parallel_groups"][0] == ["t1", "t2"]
    assert body["plan"]["tasks"][0]["status"] == "pending"


def test_plan_endpoint_asks_for_clarification(client: TestClient, mock_llm) -> None:
    mock_llm.analyze_goal.return_value = make_analysis(is_clear=False)

    body = client.post("/agent/plan", json={"goal": "help me"}).json()

    assert body["status"] == "needs_clarification"
    assert body["plan"] is None and body["clarifying_questions"]


def test_plan_endpoint_returns_502_on_llm_failure(client: TestClient, mock_llm) -> None:
    mock_llm.analyze_goal.side_effect = LLMError("quota exceeded")

    response = client.post("/agent/plan", json={"goal": "Compare AI jobs"})

    assert response.status_code == 502


def test_plan_endpoint_validates_input(client: TestClient, mock_llm) -> None:
    response = client.post("/agent/plan", json={"goal": "x"})  # min_length is 3

    assert response.status_code == 422
    mock_llm.analyze_goal.assert_not_awaited()


def test_reports_list_and_download(client: TestClient) -> None:
    response = client.get("/agent/reports")
    assert response.status_code == 200
    reports = response.json()
    assert isinstance(reports, list)

    # Test path traversal protection
    traversal = client.get("/agent/reports/..%2fconfig.py/download")
    assert traversal.status_code in {400, 404}

