"""LangGraph workflow tests: the REAL compiled graph with an in-memory checkpointer.
Only the LLM and the tool registry are mocks, so routing, interrupts, resuming,
reducers and checkpoints are all exercised for real."""

import json
from unittest.mock import create_autospec

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.evaluator import (
    Verdict,
    _JudgeOutput,
    _JudgeTask,
    evaluate_execution,
    is_retryable,
    reset_for_retry,
)
from app.agent.schemas import PlanDraft, PlannedTask, TaskStatus
from app.agent.workflow import AgentWorkflow, ApprovalDecision
from app.config import Settings
from app.llm.client import LLMError
from app.tools.base import ToolResult, ToolStatus
from app.tools.catalog import TOOL_CATALOG, TOOLS_BY_NAME
from app.tools.registry import ToolRegistry
from tests.test_executor import FAKE_ARGS, INPUT_MODELS, make_plan
from tests.test_planner import make_analysis

pytestmark = pytest.mark.anyio


def draft(*specs: tuple) -> PlanDraft:
    """specs: (id, tool, depends_on)"""
    return PlanDraft(
        strategy="s",
        tasks=[
            PlannedTask(id=i, title=f"{tool} step", description=f"Do {tool}", tool=tool,
                        depends_on=deps, priority="high", expected_output="result")
            for i, tool, deps in specs
        ],
    )


@pytest.fixture
def registry() -> ToolRegistry:
    mock = create_autospec(ToolRegistry, instance=True)
    mock.is_available.return_value = True
    mock.available_specs.return_value = list(TOOL_CATALOG)
    mock.spec.side_effect = lambda name: TOOLS_BY_NAME[name]
    mock.input_model.side_effect = lambda name: INPUT_MODELS[name]

    async def execute(name, arguments, *, approved=False, run_id=None):
        return ToolResult(tool_name=name, status=ToolStatus.SUCCESS, output=f"{name} output")

    mock.execute.side_effect = execute
    return mock


def make_workflow(mock_llm, registry, plan_draft, judges=None, **settings) -> AgentWorkflow:
    """structured() returns: the plan draft(s) for the planner (a list = one per planning),
    the judge verdicts for the evaluator (in order), and tool args for the executor."""
    mock_llm.analyze_goal.return_value = make_analysis()
    drafts = plan_draft if isinstance(plan_draft, list) else None
    judge_queue = list(judges or [])

    async def structured(messages, schema):
        if schema is PlanDraft:
            return drafts.pop(0) if drafts is not None else plan_draft
        if schema is _JudgeOutput:
            return judge_queue.pop(0)
        return schema(**{n: FAKE_ARGS[n] for n in schema.model_fields if n in FAKE_ARGS})

    mock_llm.structured.side_effect = structured
    mock_llm.generate.return_value = "summary"
    # Graph-mechanics tests use the rule-based evaluator; the LLM judge has its own tests.
    options = {"google_api_key": "k", "agent_retry_delay_seconds": 0, "evaluation_mode": "rules"} | settings
    return AgentWorkflow(
        llm_factory=lambda: mock_llm, registry=registry,
        settings=Settings(_env_file=None, **options), checkpointer=InMemorySaver(),
    )


def tools_executed(registry) -> list[str]:
    return [c.args[0] for c in registry.execute.await_args_list]


# --------------------------------------------------------------- happy path
async def test_full_run_completes_with_report(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(
        ("t1", "web_search", []), ("t2", "web_search", []),
        ("t3", "llm_analysis", ["t1", "t2"]), ("t4", "generate_report", ["t3"]),
    ))

    run_id = await wf.start("Compare AI jobs")
    view = await wf.get(run_id)

    assert view.status == "completed" and view.next_nodes == []
    assert view.final_output == "generate_report output"
    assert len(view.records) == 4  # the operator.add reducer APPENDED each wave's records
    assert view.steps_used == 4 and view.evaluation["verdict"] == "accept"


async def test_one_checkpoint_per_wave(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(
        ("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "generate_report", ["t2"]),
    ))

    run_id = await wf.start("goal")
    history = [s async for s in wf.graph.aget_state_history(wf._config(run_id))]

    # 3 sequential waves -> the graph was about to run "execute" 3 times, each time
    # from a saved checkpoint. A crash would lose at most one wave.
    assert sum(1 for s in history if s.next == ("execute",)) == 3


async def test_state_is_plain_json(mock_llm, registry) -> None:
    """Checkpoints must contain only JSON-native types: portable and safe to load.
    (An Enum in the state triggered LangGraph's 'unregistered type' warning in a live run.)"""
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])))
    run_id = await wf.start("goal")
    values = (await wf.graph.aget_state(wf._config(run_id))).values

    def check(value) -> None:
        assert type(value) in (str, int, float, bool, type(None), list, dict), type(value)
        for item in value.values() if isinstance(value, dict) else value if isinstance(value, list) else []:
            check(item)

    check(values)
    json.dumps(values)


# ------------------------------------------------------------ human-in-loop
async def test_run_pauses_for_approval_then_resumes(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(
        ("t1", "web_search", []), ("t2", "send_email", ["t1"]), ("t3", "generate_report", ["t2"]),
    ))

    run_id = await wf.start("Find jobs and email my mentor")
    paused = await wf.get(run_id)

    assert paused.status == "waiting_approval" and paused.next_nodes == ["approval"]
    assert [t["id"] for t in paused.pending_approvals] == ["t2"]
    assert "send_email" not in tools_executed(registry)  # nothing sensitive ran

    await wf.approve(run_id, ApprovalDecision(approved=["t2"]))
    done = await wf.get(run_id)

    assert done.status == "completed"
    email_call = next(c for c in registry.execute.await_args_list if c.args[0] == "send_email")
    assert email_call.kwargs["approved"] is True


async def test_not_approved_means_rejected(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(
        ("t1", "web_search", []), ("t2", "send_email", ["t1"]), ("t3", "generate_report", ["t2"]),
    ))
    run_id = await wf.start("goal")

    await wf.approve(run_id, ApprovalDecision(approved=[]))  # silence never means yes
    view = await wf.get(run_id)

    statuses = {t["id"]: (t["status"], t["error"]) for t in view.plan["tasks"]}
    assert statuses["t2"] == ("skipped", "Rejected by the user.")
    assert statuses["t3"][0] == "skipped"
    assert view.status == "partial"
    assert "send_email" not in tools_executed(registry)


# ------------------------------------------------------------- end states
async def test_unclear_goal_ends_after_planning(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, None)
    mock_llm.analyze_goal.return_value = make_analysis(is_clear=False)

    view = await wf.get(await wf.start("help me"))

    assert view.status == "needs_clarification" and view.plan is None
    assert view.planning["clarifying_questions"] == ["Which city?", "Which role?"]
    registry.execute.assert_not_awaited()


async def test_planning_failure_becomes_error_status(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, None)
    mock_llm.analyze_goal.side_effect = LLMError("quota exceeded")

    view = await wf.get(await wf.start("goal"))

    assert view.status == "error" and "quota exceeded" in view.error


# --------------------------------------------------------------- evaluator
async def test_evaluator_retries_failed_tasks_once(mock_llm, registry) -> None:
    results = [
        ToolResult(tool_name="web_search", status=ToolStatus.ERROR, error="rate limited"),
        ToolResult(tool_name="web_search", status=ToolStatus.SUCCESS, output="found it"),
    ]
    registry.execute.side_effect = results
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])), max_task_retries=0)

    view = await wf.get(await wf.start("goal"))

    assert view.status == "completed"  # failed in round 1, fixed by the evaluator's retry round
    assert registry.execute.await_count == 2


async def test_evaluator_gives_up_after_its_rounds(mock_llm, registry) -> None:
    async def search_always_fails(name, arguments, *, approved=False, run_id=None):
        # An ASYNC function: AsyncMock awaits it. (A lambda returning a coroutine would
        # be handed back un-awaited, the same mistake explained in Phase 7.)
        if name == "web_search":
            return ToolResult(tool_name=name, status=ToolStatus.ERROR, error="down")
        return ToolResult(tool_name=name, status=ToolStatus.SUCCESS, output="ok")

    registry.execute.side_effect = search_always_fails
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", []), ("t2", "calculator", [])),
                       max_task_retries=0, max_evaluation_rounds=1)

    view = await wf.get(await wf.start("goal"))

    assert view.status == "partial"
    assert "used up" in view.evaluation["reason"]
    assert tools_executed(registry).count("web_search") == 2  # first round + one retry round


# ------------------------------------------------- crash + resume (durability)
async def test_crashed_run_resumes_without_repeating_finished_work(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", []), ("t2", "calculator", ["t1"])))
    crash = {"on": True}

    async def execute(name, arguments, *, approved=False, run_id=None):
        if name == "calculator" and crash["on"]:
            raise RuntimeError("server lost power")  # unexpected: escapes the node
        return ToolResult(tool_name=name, status=ToolStatus.SUCCESS, output=f"{name} output")

    registry.execute.side_effect = execute

    run_id = await wf.start_in_background("goal")
    await wf._background[run_id]  # wait for the worker to crash
    crashed = await wf.get(run_id)

    assert crashed.resumable is True and crashed.next_nodes == ["execute"]
    assert "server lost power" in crashed.error
    assert {t["id"]: t["status"] for t in crashed.plan["tasks"]}["t1"] == "completed"  # checkpointed

    crash["on"] = False
    wf.continue_in_background(run_id)
    await wf._background[run_id]
    resumed = await wf.get(run_id)

    assert resumed.status == "completed" and resumed.error is None
    assert tools_executed(registry).count("web_search") == 1  # t1 was NOT repeated


async def test_list_runs_newest_first(mock_llm, registry) -> None:
    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])))
    first = await wf.start("first goal", run_id="run-a")
    second = await wf.start("second goal", run_id="run-b")
    # created_at has 1-second resolution: make the order unambiguous for the test.
    await wf.graph.aupdate_state(wf._config(first), {"created_at": "2026-01-01T00:00:00+00:00"}, as_node="finalize")

    runs = await wf.list_runs()

    assert [r.run_id for r in runs] == [second, first]


async def test_unknown_run_is_none(mock_llm, registry) -> None:
    assert await make_workflow(mock_llm, registry, None).get("nope") is None


# ---------------------------------------------------------- evaluator units
def test_evaluate_execution_rules() -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "send_email", []))
    plan.get_task("t1").status, plan.get_task("t1").error = TaskStatus.FAILED, "timeout"
    plan.get_task("t2").status, plan.get_task("t2").error = TaskStatus.FAILED, "Tool 'send_email' is not available."

    retry = evaluate_execution(plan, rounds_used=0, max_rounds=1)
    used_up = evaluate_execution(plan, rounds_used=1, max_rounds=1)

    assert retry.verdict == Verdict.RETRY_TASKS and retry.retry_task_ids == ["t1"]  # t2 can't be fixed
    assert used_up.verdict == Verdict.ACCEPT
    assert is_retryable("rate limited") and not is_retryable("Access denied: ...")


def test_reset_for_retry_unskips_dependents_but_not_rejections() -> None:
    plan = make_plan(("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]),
                     ("t3", "generate_report", ["t2"]), ("t4", "send_email", []))
    plan.get_task("t1").status = TaskStatus.FAILED
    for tid in ("t2", "t3"):
        plan.get_task(tid).status = TaskStatus.SKIPPED
        plan.get_task(tid).error = "Skipped: dependency x failed."
    plan.get_task("t4").status, plan.get_task("t4").error = TaskStatus.SKIPPED, "Rejected by the user."

    reset_for_retry(plan, ["t1"])

    assert [plan.get_task(t).status for t in ("t1", "t2", "t3", "t4")] == [
        TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.SKIPPED,
    ]


# ------------------------------------------------ self-evaluation (Phase 9)
def verdict(task_ids, *, passed=True, score=9, goal_achieved=True, viable=True, issues=()) -> _JudgeOutput:
    return _JudgeOutput(
        tasks=[_JudgeTask(task_id=t, passed=passed, score=score, issues=list(issues)) for t in task_ids],
        goal_achieved=goal_achieved, plan_is_viable=viable, summary="web_search can't find this; use another tool.",
    )


async def test_replan_builds_and_runs_a_new_plan(mock_llm, registry) -> None:
    first, second = draft(("t1", "web_search", [])), draft(("t1", "calculator", []))
    judges = [
        verdict(["t1"], passed=False, score=1, goal_achieved=False, viable=False, issues=["irrelevant results"]),
        verdict(["t1"]),
    ]
    wf = make_workflow(mock_llm, registry, [first, second], judges, evaluation_mode="llm")

    view = await wf.get(await wf.start("goal"))

    assert view.status == "completed" and view.replans == 1
    assert [t["tool"] for t in view.plan["tasks"]] == ["calculator"]  # the NEW plan ran
    assert [e["verdict"] for e in view.evaluation_history] == ["replan", "accept"]
    # Find calls by their schema, not by position (plan, args, judge, plan, ... interleave).
    planning_calls = [c for c in mock_llm.structured.await_args_list if c.args[1] is PlanDraft]
    second_planning_prompt = planning_calls[1].args[0][-1].content
    assert "did NOT work" in second_planning_prompt and "irrelevant results" in second_planning_prompt


async def test_open_issues_are_reported_in_the_final_output(mock_llm, registry) -> None:
    async def execute(name, arguments, *, approved=False, run_id=None):
        output = {"web_search": "393 jobs found", "generate_report": "# Report\n393 jobs and 2,500 internships"}[name]
        return ToolResult(tool_name=name, status=ToolStatus.SUCCESS, output=output)

    registry.execute.side_effect = execute
    wf = make_workflow(
        mock_llm, registry, draft(("t1", "web_search", []), ("t2", "generate_report", ["t1"])),
        [verdict(["t1", "t2"])], evaluation_mode="llm", max_evaluation_rounds=0,  # no retry budget
    )

    view = await wf.get(await wf.start("goal"))

    assert view.evaluation["verdict"] == "accept" and view.evaluation["quality_score"] == 9.0
    assert "## Verification notes (automatic)" in view.final_output
    assert "2,500" in view.final_output.split("Verification notes")[1]


async def test_a_just_started_run_is_visible_before_its_first_checkpoint(mock_llm, registry) -> None:
    import asyncio

    release = asyncio.Event()

    async def slow_analysis(goal):  # planning hasn't produced a checkpoint yet
        await release.wait()
        return make_analysis()

    wf = make_workflow(mock_llm, registry, draft(("t1", "web_search", [])))
    mock_llm.analyze_goal.side_effect = slow_analysis
    run_id = await wf.start_in_background("goal")
    await asyncio.sleep(0)  # let the worker start

    early = await wf.get(run_id)
    release.set()
    await wf._background[run_id]

    assert (early.status, early.running, early.goal) == ("planning", True, "goal")
    assert (await wf.get(run_id)).status == "completed"
