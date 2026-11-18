"""Run-history tests: RunRepository (crud.py), user scoping, and the workflow writing
its history into the tasks / task_steps / tool_logs tables (in-memory SQLite)."""

import pytest
from sqlalchemy import select

from app.agent.schemas import TaskStatus
from app.database.connection import Database
from app.database.crud import RunRepository
from app.database.models import Memory, User
from app.memory.long_term import LongTermMemory
from app.safety.approval import ApprovalStore
from tests.test_executor import make_plan
from tests.test_workflow import draft, make_workflow, registry  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio


@pytest.fixture
def database() -> Database:
    db = Database("sqlite://")
    db.create_tables()
    return db


@pytest.fixture
def repository(database: Database) -> RunRepository:
    return RunRepository(database)


async def test_run_steps_and_tool_logs_round_trip(repository: RunRepository) -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "generate_report", ["t1"]))
    plan.get_task("t1").status, plan.get_task("t1").result, plan.get_task("t1").attempts = (
        TaskStatus.COMPLETED, "393 jobs", 2,
    )

    await repository.create_run("run-1", "Compare AI jobs")
    await repository.sync_plan("run-1", plan)
    await repository.add_tool_logs("run-1", [
        {"task_id": "t1", "attempt": 1, "tool": "web_search", "arguments": {"query": "ai jobs"},
         "status": "error", "output_preview": "", "error": "timeout", "duration_ms": 1200.6},
        {"task_id": "t1", "attempt": 2, "tool": "web_search", "arguments": {"query": "ai jobs"},
         "status": "success", "output_preview": "393 jobs", "duration_ms": 800, "security_flags": ["role hijack"]},
    ])
    await repository.update_run("run-1", status="completed", steps_used=2, final_output="# Report", quality_score=9.0)

    history = await repository.history("run-1")

    assert (history.run.status, history.run.steps_used, history.run.quality_score) == ("completed", 2, 9.0)
    assert history.final_output == "# Report"
    assert [(s.step_number, s.step_key, s.status, s.attempts) for s in history.steps] == [
        (1, "t1", "completed", 2), (2, "t2", "pending", 0),
    ]
    assert history.steps[0].result == {"output": "393 jobs", "feedback": None}
    assert [(log.attempt, log.status, log.execution_time_ms) for log in history.tool_logs] == [
        (1, "error", 1200), (2, "success", 800),
    ]
    assert history.tool_logs[1].output_data["security_flags"] == ["role hijack"]


async def test_attempts_continue_across_evaluation_rounds(repository: RunRepository) -> None:
    def call(attempt: int) -> dict:
        return {"task_id": "t2", "attempt": attempt, "tool": "generate_report", "status": "success"}

    await repository.add_tool_logs("run-1", [call(1), call(2)])  # round 1: failed once, then OK
    await repository.add_tool_logs("run-1", [call(1)])           # evaluator retry: executor restarts at 1

    assert [log.attempt for log in (await repository.history("run-1")).tool_logs] == [1, 2, 3]


async def test_sync_plan_is_idempotent_and_handles_replans(repository: RunRepository) -> None:
    first = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]))
    await repository.sync_plan("run-1", first)
    await repository.sync_plan("run-1", first)  # repeated (a node re-ran): no duplicates

    # A re-plan where t2 now runs FIRST: the UNIQUE (task_id, step_number) must not collide.
    second = make_plan(("t2", "calculator", []), ("t1", "generate_report", ["t2"]))
    await repository.sync_plan("run-1", second)

    steps = (await repository.history("run-1")).steps
    assert [(s.step_number, s.step_key, s.tool_name) for s in steps] == [(1, "t2", "calculator"), (2, "t1", "generate_report")]


async def test_unknown_fields_are_rejected(repository: RunRepository) -> None:
    with pytest.raises(ValueError, match="Unknown run fields"):
        await repository.update_run("run-1", is_admin=True)


async def test_list_runs_newest_first_and_missing_history(repository: RunRepository) -> None:
    await repository.create_run("old", "first goal")
    await repository.create_run("new", "second goal")

    assert [r.run_id for r in await repository.list_runs()] == ["new", "old"]
    assert await repository.history("nope") is None


async def test_approvals_are_linked_to_the_run_row(database: Database, repository: RunRepository) -> None:
    await repository.create_run("run-1", "Email my mentor")
    store = ApprovalStore(database)

    await store.request("run-1", "t2", "send_email", "Email", {"to": ["m@example.com"]})

    record = (await store.list_records(run_id="run-1"))[0]
    assert (record.run_id, record.task_id, record.tool) == ("run-1", "t2", "send_email")


async def test_memories_are_scoped_to_their_owner(database: Database) -> None:
    memory = LongTermMemory(database)
    mine, _ = await memory.add("User likes chai.")
    with database.session() as s:  # someone else's memory, inserted directly
        other = User(username="other", email="other@example.com", password_hash="x")
        s.add(other)
        s.flush()
        s.add(Memory(user_id=other.id, content="Other user's secret plan.", category="other"))

    visible = [m.content for m in await memory.list_memories()]

    assert visible == ["User likes chai."]
    with database.session() as s:
        other_id = s.scalar(select(Memory.id).where(Memory.content == "Other user's secret plan."))
    assert await memory.get(other_id) is None and await memory.delete(other_id) is False
    assert mine.id != other_id


# ------------------------------------------------------------------- workflow
async def test_workflow_writes_its_history(mock_llm, registry, database: Database) -> None:  # noqa: F811
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", []), ("t2", "generate_report", ["t1"])))
    wf._history = RunRepository(database)

    run_id = await wf.start("Compare AI jobs")
    history = await wf.history(run_id)

    assert history.run.goal == "Compare AI jobs" and history.run.status == "completed"
    assert history.final_output == "generate_report output"
    assert [s.status for s in history.steps] == ["completed", "completed"]
    assert [log.tool_name for log in history.tool_logs] == ["web_search", "generate_report"]
    assert [v.run_id for v in await wf.list_runs()] == [run_id]  # listed from the DB index


async def test_history_failures_never_break_a_run(mock_llm, registry) -> None:  # noqa: F811
    from unittest.mock import create_autospec

    flaky = create_autospec(RunRepository, instance=True)  # create_run works...
    flaky.sync_plan.side_effect = RuntimeError("database down")  # ...later writes fail
    flaky.add_tool_logs.side_effect = RuntimeError("database down")
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])))
    wf._history = flaky

    view = await wf.get(await wf.start("goal"))

    assert view.status == "completed"  # the checkpoint is the source of truth


async def test_a_run_without_an_owner_record_does_not_start(mock_llm, registry) -> None:  # noqa: F811
    from unittest.mock import create_autospec

    broken = create_autospec(RunRepository, instance=True)
    broken.create_run.side_effect = RuntimeError("database down")
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])))
    wf._history = broken

    with pytest.raises(RuntimeError):
        await wf.start_in_background("goal")

    assert wf._background == {}  # nothing was started
    mock_llm.structured.assert_not_called()  # no planning (no LLM spend) either
