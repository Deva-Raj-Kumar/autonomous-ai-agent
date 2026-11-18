"""API tests for the LangGraph run endpoints. AgentWorkflow is a create_autospec mock."""

from collections.abc import Iterator
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from app.agent.workflow import AgentWorkflow, RunView
from app.api.routes import get_workflow
from app.main import app


def view(**overrides) -> RunView:
    data = {"run_id": "r1", "goal": "goal", "status": "completed", "running": False, "next_nodes": []}
    return RunView(**(data | overrides))


WAITING = view(status="waiting_approval", next_nodes=["approval"],
               pending_approvals=[{"id": "t2", "title": "Email", "tool": "send_email", "description": "d"}])


@pytest.fixture
def workflow() -> AgentWorkflow:
    return create_autospec(AgentWorkflow, instance=True)


@pytest.fixture
def client(workflow) -> Iterator[TestClient]:
    app.dependency_overrides[get_workflow] = lambda: workflow
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_start_in_background_returns_202(client: TestClient, workflow) -> None:
    workflow.start_in_background.return_value = "r1"

    response = client.post("/agent/runs", json={"goal": "Compare AI jobs"})

    assert response.status_code == 202
    assert response.json()["links"]["self"] == "/agent/runs/r1"
    workflow.start_in_background.assert_called_once_with("Compare AI jobs")


def test_synchronous_run_returns_the_final_view(client: TestClient, workflow) -> None:
    workflow.start.return_value = "r1"
    workflow.get.return_value = view(final_output="# Report")

    assert client.post("/agent/run", json={"goal": "Compare AI jobs"}).json()["final_output"] == "# Report"


def test_get_and_list_runs(client: TestClient, workflow) -> None:
    workflow.get.side_effect = lambda run_id: view() if run_id == "r1" else None
    workflow.list_runs.return_value = [view()]

    assert client.get("/agent/runs/r1").json()["status"] == "completed"
    assert client.get("/agent/runs/missing").status_code == 404
    assert client.get("/agent/runs").json()[0]["run_id"] == "r1"


def test_approval_resumes_in_background(client: TestClient, workflow) -> None:
    workflow.get.return_value = WAITING

    # The client tries to put someone else's name in the audit trail.
    response = client.post("/agent/runs/r1/approval", json={"approved": ["t2"], "decided_by": "the-ceo"})

    assert response.status_code == 202
    # The server records the LOGGED-IN user (from the verified token) instead.
    decision = workflow.approve_in_background.call_args.args[1]
    assert decision.approved == ["t2"]
    assert decision.decided_by.startswith("user:") and decision.decided_by.endswith(":local")


def test_approval_rejects_unknown_task_ids(client: TestClient, workflow) -> None:
    workflow.get.return_value = WAITING

    response = client.post("/agent/runs/r1/approval", json={"approved": ["t9"]})

    assert response.status_code == 422
    workflow.approve_in_background.assert_not_called()


def test_approval_when_not_waiting_is_409(client: TestClient, workflow) -> None:
    workflow.get.return_value = view()  # finished

    assert client.post("/agent/runs/r1/approval", json={"approved": []}).status_code == 409


def test_continue_only_for_interrupted_runs(client: TestClient, workflow) -> None:
    workflow.get.return_value = view()
    assert client.post("/agent/runs/r1/continue").status_code == 409

    workflow.get.return_value = view(status="executing", next_nodes=["execute"], resumable=True)
    assert client.post("/agent/runs/r1/continue").status_code == 202
    workflow.continue_in_background.assert_called_once_with("r1")


def test_workflow_unavailable_is_503() -> None:
    with TestClient(app) as client:
        client.app.state.workflow = None  # e.g. no LLM key configured
        assert client.get("/agent/runs").status_code == 503


# ------------------------------------------------------------ history (Phase 11)
def test_someone_elses_run_looks_missing(client: TestClient, workflow) -> None:
    workflow.owns.return_value = False  # the run exists, but belongs to another user
    workflow.get.return_value = WAITING

    assert client.get("/agent/runs/r1").status_code == 404
    assert client.post("/agent/runs/r1/approval", json={"approved": ["t2"]}).status_code == 404
    workflow.get.assert_not_called()  # the checkpoint isn't even loaded
    workflow.approve_in_background.assert_not_called()


def test_run_history_from_the_database(client: TestClient) -> None:
    from app.api.routes import get_run_repository
    from app.database.crud import RunHistory, RunRepository, RunSummaryRow

    repository = create_autospec(RunRepository, instance=True)
    summary = RunSummaryRow(run_id="r1", goal="g", status="completed", steps_used=1,
                            quality_score=8.5, created_at=None, updated_at=None)
    repository.history.side_effect = lambda run_id: (
        RunHistory(run=summary, final_output="# R", error=None, steps=[], tool_logs=[]) if run_id == "r1" else None
    )
    app.dependency_overrides[get_run_repository] = lambda: repository

    assert client.get("/agent/runs/r1/history").json()["run"]["quality_score"] == 8.5
    assert client.get("/agent/runs/missing/history").status_code == 404


def test_run_history_needs_a_database(client: TestClient) -> None:
    client.app.state.run_repository = None  # what the lifespan sets when the DB is unusable

    response = client.get("/agent/runs/r1/history")

    assert response.status_code == 503 and "alembic upgrade head" in response.json()["detail"]
