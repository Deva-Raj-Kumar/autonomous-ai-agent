"""TaskExecutor tests. The ToolRegistry and LLMService are create_autospec mocks, so each
test decides exactly when a tool succeeds, fails, hangs or needs approval."""

import asyncio
from unittest.mock import create_autospec

import pytest

from app.agent.executor import ArgumentBuilder, TaskExecutor, ancestors
from app.agent.schemas import ExecutionStatus, Plan, Task, TaskStatus
from app.llm.client import LLMError
from app.tools.base import ToolResult, ToolStatus
from app.tools.calculator import CalculatorInput
from app.tools.catalog import TOOLS_BY_NAME
from app.tools.database_tool import SaveInput
from app.tools.llm_tools import ReasoningInput
from app.tools.registry import ToolRegistry
from app.tools.web_search import WebSearchInput
from tests.test_planner import make_analysis

pytestmark = pytest.mark.anyio

INPUT_MODELS = {
    "web_search": WebSearchInput,
    "calculator": CalculatorInput,
    "llm_analysis": ReasoningInput,
    "generate_report": ReasoningInput,
    "save_to_database": SaveInput,
    "send_email": WebSearchInput,  # stand-in schema; send_email has no real tool
}
FAKE_ARGS = {"query": "ai jobs", "expression": "1+1", "kind": "report", "title": "My report", "content": "x"}


# ------------------------------------------------------------------ helpers
def make_plan(*specs: tuple) -> Plan:
    """specs: (id, tool, depends_on[, requires_approval])"""
    tasks = [
        Task(
            id=spec[0], title=f"{spec[1]} task", description=f"Do {spec[1]} for {spec[0]}",
            tool=spec[1], depends_on=spec[2], priority="high", expected_output="a result",
            requires_approval=spec[3] if len(spec) > 3 else False,
        )
        for spec in specs
    ]
    return Plan(goal="Test goal", analysis=make_analysis(), strategy="s", tasks=tasks)


def ok(tool: str, output: str) -> ToolResult:
    return ToolResult(tool_name=tool, status=ToolStatus.SUCCESS, output=output)


def err(tool: str, message: str = "boom") -> ToolResult:
    return ToolResult(tool_name=tool, status=ToolStatus.ERROR, error=message)


async def always_error(name, arguments=None, *, approved=False, run_id=None) -> ToolResult:
    """AsyncMock side_effect must be an ASYNC function (or a list / an exception).
    A plain lambda returning a coroutine would be handed back un-awaited."""
    return err(name)


@pytest.fixture
def registry() -> ToolRegistry:
    """Mock registry: every tool available, real specs and input models, tools succeed
    with an output naming the task's tool (override execute.side_effect per test)."""
    mock = create_autospec(ToolRegistry, instance=True)
    mock.is_available.return_value = True
    mock.spec.side_effect = lambda name: TOOLS_BY_NAME[name]
    mock.input_model.side_effect = lambda name: INPUT_MODELS[name]

    async def execute(name, arguments, *, approved=False, run_id=None):
        return ok(name, f"{name} output")

    mock.execute.side_effect = execute
    return mock


@pytest.fixture
def llm(mock_llm):
    """The argument builder's structured() call returns plausible args for any schema."""

    async def structured(messages, schema):
        return schema(**{n: FAKE_ARGS[n] for n in schema.model_fields if n in FAKE_ARGS})

    mock_llm.structured.side_effect = structured
    mock_llm.generate.return_value = "LLM summary of the results"
    return mock_llm


def executor(registry, llm, **options) -> TaskExecutor:
    options.setdefault("retry_delay_seconds", 0)  # no real waiting in tests
    return TaskExecutor(registry, llm, **options)


def executed_tools(registry) -> list[str]:
    return [call.args[0] for call in registry.execute.await_args_list]


# --------------------------------------------------------------- happy path
async def test_runs_every_task_in_dependency_order(registry, llm) -> None:
    plan = make_plan(
        ("t1", "web_search", []), ("t2", "web_search", []),
        ("t3", "llm_analysis", ["t1", "t2"]), ("t4", "generate_report", ["t3"]),
    )

    result = await executor(registry, llm).execute(plan)

    assert result.status == ExecutionStatus.COMPLETED
    assert executed_tools(registry) == ["web_search", "web_search", "llm_analysis", "generate_report"]
    assert all(t.status == TaskStatus.COMPLETED for t in result.plan.tasks)
    assert result.steps_used == 4 and len(result.records) == 4
    assert result.final_output == "generate_report output"  # the report IS the final output
    llm.generate.assert_not_awaited()  # so no extra summary call was needed


async def test_a_wave_runs_in_parallel(registry, llm) -> None:
    started, both_running = 0, asyncio.Event()

    async def execute(name, arguments, *, approved=False, run_id=None):
        nonlocal started
        started += 1
        if started == 2:
            both_running.set()
        # If tasks ran one after another, this would wait forever (and time out).
        await asyncio.wait_for(both_running.wait(), timeout=2)
        return ok(name, "done")

    registry.execute.side_effect = execute

    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", []), ("t2", "web_search", [])))

    assert result.status == ExecutionStatus.COMPLETED


async def test_max_parallel_caps_concurrency(registry, llm) -> None:
    running = peak = 0

    async def execute(name, arguments, *, approved=False, run_id=None):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return ok(name, "done")

    registry.execute.side_effect = execute
    plan = make_plan(*[(f"t{i}", "web_search", []) for i in range(1, 6)])

    await executor(registry, llm, max_parallel=2).execute(plan)

    assert peak == 2


# ---------------------------------------------------------- data passing
async def test_dependency_results_are_passed_by_code_not_by_llm(registry, llm) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        return ok(name, "SEARCH RESULT XYZ" if name == "web_search" else "report")

    registry.execute.side_effect = execute
    plan = make_plan(("t1", "web_search", []), ("t2", "generate_report", ["t1"]))

    await executor(registry, llm).execute(plan)

    report_args = registry.execute.await_args_list[1].args[1]
    assert "SEARCH RESULT XYZ" in report_args["context"]
    assert "Do generate_report for t2" in report_args["instructions"]
    llm.structured.assert_awaited_once()  # only web_search needed the LLM for its arguments


async def test_report_sees_results_of_all_ancestors(registry, llm) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        return ok(name, {"web_search": "URL https://jobs.example", "llm_analysis": "ANALYSIS"}.get(name, "report"))

    registry.execute.side_effect = execute
    plan = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "generate_report", ["t2"]))

    await executor(registry, llm).execute(plan)

    report_context = registry.execute.await_args_list[2].args[1]["context"]
    assert "ANALYSIS" in report_context and "https://jobs.example" in report_context


async def test_saved_content_is_the_dependency_output(registry, llm) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        return ok(name, "# Full Markdown report" if name == "generate_report" else "saved")

    registry.execute.side_effect = execute
    plan = make_plan(("t1", "generate_report", []), ("t2", "save_to_database", ["t1"]))

    await executor(registry, llm).execute(plan)

    save_args = registry.execute.await_args_list[1].args[1]
    assert "# Full Markdown report" in save_args["content"]
    assert save_args["title"] == "My report"  # the LLM only filled the small fields
    schema_shown_to_llm = llm.structured.await_args.args[1]
    assert "content" not in schema_shown_to_llm.model_fields


# ------------------------------------------------------------- failures
async def test_failed_attempt_is_retried_with_the_error(registry, llm) -> None:
    # side_effect as a LIST: each call returns the next item.
    registry.execute.side_effect = [err("web_search", "rate limited"), ok("web_search", "results")]

    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", [])))

    task = result.plan.get_task("t1")
    assert task.status == TaskStatus.COMPLETED and task.attempts == 2
    retry_prompt = llm.structured.await_args_list[1].args[0][-1].content
    assert "previous attempt FAILED" in retry_prompt and "rate limited" in retry_prompt
    assert [r.status for r in result.records] == ["error", "success"]


async def test_exhausted_retries_fail_the_task_and_skip_dependents(registry, llm) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        return err(name) if arguments.get("query") == "ai jobs" and name == "web_search" else ok(name, "fine")

    registry.execute.side_effect = execute
    plan = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "calculator", []))

    result = await executor(registry, llm, max_retries=2).execute(plan)

    statuses = {t.id: t.status for t in result.plan.tasks}
    assert statuses == {"t1": TaskStatus.FAILED, "t2": TaskStatus.SKIPPED, "t3": TaskStatus.COMPLETED}
    assert result.status == ExecutionStatus.PARTIAL
    assert executed_tools(registry).count("web_search") == 3  # 1 try + 2 retries
    assert "dependency t1 failed" in result.plan.get_task("t2").error


async def test_nothing_completed_means_failed(registry, llm) -> None:
    registry.execute.side_effect = always_error

    result = await executor(registry, llm, max_retries=0).execute(make_plan(("t1", "web_search", [])))

    assert result.status == ExecutionStatus.FAILED and result.final_output is None


async def test_argument_building_failure_counts_as_an_attempt(registry, llm) -> None:
    original = llm.structured.side_effect
    calls = 0

    async def flaky(messages, schema):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LLMError("model overloaded")
        return await original(messages, schema)

    llm.structured.side_effect = flaky

    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", [])))

    assert result.plan.get_task("t1").attempts == 2
    assert result.records[0].status == "error" and "model overloaded" in result.records[0].error


async def test_unavailable_tool_fails_without_using_steps(registry, llm) -> None:
    registry.is_available.side_effect = lambda name: name != "send_email"

    result = await executor(registry, llm).execute(make_plan(("t1", "send_email", [])))

    assert result.plan.get_task("t1").status == TaskStatus.FAILED
    assert result.steps_used == 0
    registry.execute.assert_not_awaited()


# --------------------------------------------------------------- approval
async def test_approval_task_waits_and_never_runs(registry, llm) -> None:
    plan = make_plan(
        ("t1", "web_search", []), ("t2", "send_email", ["t1"], True), ("t3", "generate_report", ["t2"]),
    )

    result = await executor(registry, llm).execute(plan)

    assert result.status == ExecutionStatus.WAITING_APPROVAL
    assert result.pending_approvals == ["t2"]
    assert result.plan.get_task("t3").status == TaskStatus.PENDING  # resumable, not skipped
    assert "send_email" not in executed_tools(registry)


async def test_approved_task_runs_with_the_approved_flag(registry, llm) -> None:
    plan = make_plan(("t1", "send_email", [], True))

    result = await executor(registry, llm, approved_task_ids=frozenset({"t1"})).execute(plan)

    assert result.status == ExecutionStatus.COMPLETED
    assert registry.execute.await_args.kwargs["approved"] is True


async def test_registry_refusal_overrides_the_plan(registry, llm) -> None:
    """Defense in depth: the plan says no approval needed, but the registry knows better."""
    registry.execute.return_value = ToolResult(
        tool_name="send_email", status=ToolStatus.NEEDS_APPROVAL, error="Human approval required."
    )
    registry.execute.side_effect = None  # use return_value instead of the fixture's side_effect

    result = await executor(registry, llm).execute(make_plan(("t1", "send_email", [], False)))

    assert result.plan.get_task("t1").status == TaskStatus.WAITING_APPROVAL
    assert result.status == ExecutionStatus.WAITING_APPROVAL


# ----------------------------------------------------------------- limits
async def test_step_limit_stops_the_run(registry, llm) -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "calculator", ["t1"]), ("t3", "calculator", ["t2"]))

    result = await executor(registry, llm, max_steps=2).execute(plan)

    assert result.status == ExecutionStatus.STOPPED
    assert "Step limit of 2" in result.stop_reason
    assert result.steps_used == 2
    assert result.plan.get_task("t3").status == TaskStatus.PENDING


async def test_step_limit_also_caps_retries(registry, llm) -> None:
    registry.execute.side_effect = always_error

    result = await executor(registry, llm, max_steps=2, max_retries=5).execute(make_plan(("t1", "web_search", [])))

    assert result.steps_used == 2 and result.status == ExecutionStatus.STOPPED


async def test_run_timeout_stops_a_stuck_run(registry, llm) -> None:
    async def hang(name, arguments, *, approved=False, run_id=None):
        await asyncio.sleep(10)

    registry.execute.side_effect = hang

    result = await executor(registry, llm, run_timeout_seconds=0.1).execute(make_plan(("t1", "web_search", [])))

    assert result.status == ExecutionStatus.STOPPED
    assert "time limit" in result.stop_reason
    assert result.plan.get_task("t1").status == TaskStatus.FAILED


# ----------------------------------------------------------- final output
async def test_summary_is_generated_when_there_is_no_report(registry, llm) -> None:
    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", [])))

    assert result.final_output == "LLM summary of the results"
    assert "Test goal" in llm.generate.await_args.args[0][-1].content


async def test_summary_failure_falls_back_to_last_result(registry, llm) -> None:
    llm.generate.side_effect = LLMError("down")

    result = await executor(registry, llm).execute(make_plan(("t1", "web_search", [])))

    assert result.final_output == "web_search output"


# ----------------------------------------------------------------- events
async def test_progress_events_and_broken_callbacks(registry, llm) -> None:
    events = []

    await executor(registry, llm, on_event=events.append).execute(make_plan(("t1", "web_search", [])))
    kinds = [e.kind for e in events]

    assert kinds == ["run_started", "task_started", "task_finished", "run_finished"]

    def broken(event):
        raise RuntimeError("display crashed")

    result = await executor(registry, llm, on_event=broken).execute(make_plan(("t1", "web_search", [])))
    assert result.status == ExecutionStatus.COMPLETED  # a broken display never breaks a run


async def test_long_arguments_are_shortened_in_records(registry, llm) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        return ok(name, "R" * 5_000)

    registry.execute.side_effect = execute
    plan = make_plan(("t1", "web_search", []), ("t2", "generate_report", ["t1"]))

    result = await executor(registry, llm).execute(plan)

    report_record = result.records[1]
    assert len(report_record.arguments["context"]) <= 303 and report_record.arguments["context"].endswith("...")
    assert len(report_record.output_preview) == 300


# ------------------------------------------------------------ pure helpers
def test_ancestors_are_transitive() -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "generate_report", ["t2"]))

    assert ancestors(plan, plan.get_task("t3")) == {"t1", "t2"}


def test_auto_fields_leave_missing_data_to_the_llm(registry, llm) -> None:
    task = make_plan(("t1", "save_to_database", [])).get_task("t1")
    builder = ArgumentBuilder(llm, registry)

    assert ArgumentBuilder.auto_fields(task, dependency_results="") == {}  # no data: don't fake it
    assert "content" in builder.llm_model("save_to_database", frozenset()).model_fields
    assert builder.llm_model("llm_analysis", frozenset({"instructions", "context"})) is None
