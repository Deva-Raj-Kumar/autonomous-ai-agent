"""APPROVE WHAT YOU SEE: end-to-end approval behaviour in the executor and the workflow.

Fixtures are imported from the executor/workflow test modules (pytest discovers
fixtures that are imported into a test module).
"""

from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from app.agent.schemas import TaskStatus
from app.agent.workflow import AgentWorkflow, ApprovalDecision
from app.api.routes import get_approval_store
from app.database.connection import Database
from app.main import app
from app.safety.approval import ApprovalStore
from app.tools.base import ToolResult, ToolStatus
from app.tools.catalog import TOOL_CATALOG
from tests.test_executor import executor, llm, make_plan, registry  # noqa: F401  (fixtures)
from tests.test_workflow import draft, make_workflow  # noqa: F401

pytestmark = pytest.mark.anyio


def executed(registry) -> list[tuple[str, dict, bool]]:
    return [(c.args[0], c.args[1], c.kwargs["approved"]) for c in registry.execute.await_args_list]


# ----------------------------------------------------------------- executor
async def test_arguments_are_built_and_shown_before_the_pause(registry, llm) -> None:
    result = await executor(registry, llm).execute(make_plan(("t1", "send_email", [], True)))

    task = result.plan.get_task("t1")
    assert task.status == TaskStatus.WAITING_APPROVAL
    assert task.proposed_arguments == {"query": "ai jobs", "max_results": None}  # exactly what will run
    registry.execute.assert_not_awaited()  # nothing ran
    assert result.steps_used == 0  # preparing arguments is not a tool attempt


async def test_approved_task_runs_exactly_the_shown_arguments(registry, llm) -> None:
    plan = make_plan(("t1", "send_email", [], True))
    plan.get_task("t1").status = TaskStatus.PENDING
    plan.get_task("t1").proposed_arguments = {"query": "the APPROVED text", "max_results": 3}

    await executor(registry, llm, approved_task_ids=frozenset({"t1"})).execute(plan)

    assert executed(registry) == [("send_email", {"query": "the APPROVED text", "max_results": 3}, True)]
    llm.structured.assert_not_awaited()  # never regenerated, so nothing unseen can run


async def test_approved_arguments_are_reused_on_retry_never_regenerated(registry, llm) -> None:
    plan = make_plan(("t1", "send_email", [], True))
    plan.get_task("t1").status = TaskStatus.PENDING
    plan.get_task("t1").proposed_arguments = {"query": "approved", "max_results": None}
    registry.execute.side_effect = [
        ToolResult(tool_name="send_email", status=ToolStatus.ERROR, error="smtp timeout"),
        ToolResult(tool_name="send_email", status=ToolStatus.SUCCESS, output="sent"),
    ]

    result = await executor(registry, llm, approved_task_ids=frozenset({"t1"})).execute(plan)

    assert result.plan.get_task("t1").status == TaskStatus.COMPLETED
    assert [args for _, args, _ in executed(registry)] == [{"query": "approved", "max_results": None}] * 2
    llm.structured.assert_not_awaited()


async def test_policy_denial_is_not_retried(registry, llm) -> None:
    registry.execute.side_effect = [
        ToolResult(tool_name="web_search", status=ToolStatus.DENIED, error="Permission denied: budget used up.")
    ]

    result = await executor(registry, llm, max_retries=3).execute(make_plan(("t1", "web_search", [])))

    assert result.plan.get_task("t1").status == TaskStatus.FAILED
    assert registry.execute.await_count == 1  # retrying can't change a policy


async def test_rate_limit_is_retried(registry, llm) -> None:
    registry.execute.side_effect = [
        ToolResult(tool_name="web_search", status=ToolStatus.DENIED, error="Rate limit: retry in 5s."),
        ToolResult(tool_name="web_search", status=ToolStatus.SUCCESS, output="results"),
    ]

    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", [])))

    assert result.plan.get_task("t1").status == TaskStatus.COMPLETED


# ----------------------------------------------------------------- workflow
def workflow_with_store(mock_llm, registry, plan_draft, **settings) -> tuple[AgentWorkflow, ApprovalStore]:
    database = Database("sqlite://")
    database.create_tables()
    store = ApprovalStore(database)
    # The executor tests' registry fixture doesn't list tools for the PLANNER: add them.
    registry.available_specs.return_value = list(TOOL_CATALOG)
    wf = make_workflow(mock_llm, registry, plan_draft, **settings)
    wf._approvals = store
    return wf, store


async def test_pause_shows_arguments_and_records_the_audit_trail(mock_llm, registry) -> None:
    wf, store = workflow_with_store(mock_llm, registry, draft(("t1", "web_search", []), ("t2", "send_email", ["t1"])))

    run_id = await wf.start("Find jobs and email my mentor")
    paused = await wf.get(run_id)

    assert paused.pending_approvals[0]["arguments"] == {"query": "ai jobs", "max_results": None}
    pending = await store.list_records(status="pending")
    assert [(r.task_id, r.tool) for r in pending] == [("t2", "send_email")]

    await wf.approve(run_id, ApprovalDecision(approved=["t2"], decided_by="cli"))

    records = await store.list_records(run_id=run_id)
    assert len(records) == 1  # the approval node ran twice (pause + resume): still ONE record
    assert (records[0].status, records[0].decided_by) == ("approved", "cli")
    email_call = next(c for c in registry.execute.await_args_list if c.args[0] == "send_email")
    assert email_call.args[1] == records[0].arguments  # what ran == what was recorded == what was shown


async def test_evaluator_retry_revokes_the_old_approval(mock_llm, registry) -> None:
    wf, _ = workflow_with_store(mock_llm, registry, draft(("t1", "send_email", [])),
                                max_task_retries=0, max_evaluation_rounds=1)
    registry.execute.side_effect = [ToolResult(tool_name="send_email", status=ToolStatus.ERROR, error="smtp down")]

    run_id = await wf.start("goal")
    await wf.approve(run_id, ApprovalDecision(approved=["t1"]))  # approve, then it fails
    view = await wf.get(run_id)

    # The evaluator retried t1 with NEW arguments: that needs a NEW approval, not the old one.
    assert view.status == "waiting_approval" and [t["id"] for t in view.pending_approvals] == ["t1"]
    assert registry.execute.await_count == 1  # the retry did not run on the old approval


# ---------------------------------------------------------------------- API
def test_approvals_endpoint_lists_the_audit_trail() -> None:
    store = create_autospec(ApprovalStore, instance=True)
    store.list_records.return_value = []
    app.dependency_overrides[get_approval_store] = lambda: store
    try:
        with TestClient(app) as client:
            response = client.get("/approvals", params={"status": "pending"})
            bad = client.get("/approvals", params={"status": "maybe"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200 and bad.status_code == 422
    store.list_records.assert_awaited_once_with(status="pending", run_id=None, limit=100)


def test_approvals_need_a_database() -> None:
    with TestClient(app) as client:
        client.app.state.approval_store = None
        assert client.get("/approvals").status_code == 503
