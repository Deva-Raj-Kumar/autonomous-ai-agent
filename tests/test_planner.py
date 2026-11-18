"""Tests for the Planner (with a mocked LLMService) and the Plan model."""

import pytest
from pydantic import ValidationError

from app.agent.planner import Planner, PlanningError
from app.agent.schemas import Plan, PlanDraft, PlannedTask, Task, TaskStatus
from app.llm.schemas import GoalAnalysis


def make_analysis(is_clear: bool = True) -> GoalAnalysis:
    return GoalAnalysis(
        summary="Compare AI fresher jobs in two cities and save a report.",
        category="research",
        deliverables=["report"],
        required_capabilities=["web_search", "report_generation", "database"],
        is_clear=is_clear,
        clarifying_questions=[] if is_clear else ["Which city?", "Which role?"],
    )


def task(task_id: str, tool: str, deps: list[str] | None = None, priority: str = "high"):
    return PlannedTask(
        id=task_id,
        title=f"{tool} step",
        description=f"Run {tool}",
        tool=tool,
        depends_on=deps or [],
        priority=priority,
        expected_output="a result",
    )


GOOD_DRAFT = PlanDraft(
    strategy="Search both cities in parallel, compare, report, save.",
    tasks=[
        task("t1", "web_search"),
        task("t2", "web_search"),
        task("t3", "llm_analysis", ["t1", "t2"]),
        task("t4", "generate_report", ["t3"]),
        task("t5", "save_to_database", ["t4"], priority="medium"),
    ],
)


def planner_with(mock_llm, *drafts, analysis: GoalAnalysis | None = None, **kwargs) -> Planner:
    """Configure the mock: analyze_goal returns `analysis`; structured returns `drafts`
    one per call (side_effect with a list = a different return value per call)."""
    mock_llm.analyze_goal.return_value = analysis or make_analysis()
    mock_llm.structured.side_effect = list(drafts)
    return Planner(mock_llm, **kwargs)


# ---------------------------------------------------------------- Planner
@pytest.mark.anyio
async def test_creates_plan_on_first_attempt(mock_llm) -> None:
    planner = planner_with(mock_llm, GOOD_DRAFT)

    result = await planner.create_plan("Compare AI jobs in Bengaluru and Hyderabad")

    assert result.status == "planned" and result.attempts == 1
    assert result.plan.parallel_groups == [["t1", "t2"], ["t3"], ["t4"], ["t5"]]
    assert all(t.status == TaskStatus.PENDING for t in result.plan.tasks)
    mock_llm.analyze_goal.assert_awaited_once_with("Compare AI jobs in Bengaluru and Hyderabad")
    # structured() was asked for a PlanDraft (2nd positional argument is the schema).
    assert mock_llm.structured.await_args.args[1] is PlanDraft


@pytest.mark.anyio
async def test_unclear_goal_returns_questions_without_planning(mock_llm) -> None:
    planner = planner_with(mock_llm, analysis=make_analysis(is_clear=False))

    result = await planner.create_plan("help me")

    assert result.status == "needs_clarification" and result.plan is None
    assert result.clarifying_questions == ["Which city?", "Which role?"]
    mock_llm.structured.assert_not_awaited()  # no plan was drafted: no wasted LLM call


@pytest.mark.anyio
async def test_invalid_draft_is_repaired_with_feedback(mock_llm) -> None:
    bad_draft = PlanDraft(
        strategy="oops",
        tasks=[task("t1", "google_search"), task("t2", "generate_report", ["t1"])],
    )
    planner = planner_with(mock_llm, bad_draft, GOOD_DRAFT)

    result = await planner.create_plan("Compare AI jobs")

    assert result.status == "planned" and result.attempts == 2
    assert mock_llm.structured.await_count == 2
    # The repair request (last message of the 2nd call) told the model what was wrong.
    repair_message = mock_llm.structured.await_args_list[1].args[0][-1].content
    assert "unknown tool 'google_search'" in repair_message
    assert "web_search" in repair_message  # and listed the valid tools


@pytest.mark.anyio
async def test_gives_up_after_max_attempts(mock_llm) -> None:
    cyclic = PlanDraft(
        strategy="loop",
        tasks=[task("t1", "web_search", ["t2"]), task("t2", "llm_analysis", ["t1"])],
    )
    planner = planner_with(mock_llm, cyclic, cyclic, max_attempts=2)

    with pytest.raises(PlanningError, match="2 attempts.*Circular dependency"):
        await planner.create_plan("anything")
    assert mock_llm.structured.await_count == 2


@pytest.mark.anyio
async def test_approval_comes_from_catalog_not_llm(mock_llm) -> None:
    draft = PlanDraft(
        strategy="search, summarize, email",
        tasks=[
            task("t1", "web_search"),
            task("t2", "llm_analysis", ["t1"]),
            task("t3", "send_email", ["t2"]),
        ],
    )
    planner = planner_with(mock_llm, draft)

    result = await planner.create_plan("Find internships and email my mentor")

    approvals = {t.id: t.requires_approval for t in result.plan.tasks}
    assert approvals == {"t1": False, "t2": False, "t3": True}


def test_too_many_tasks_rejected(mock_llm) -> None:
    errors = Planner(mock_llm, max_tasks=3).validate_draft(GOOD_DRAFT)  # 5 tasks

    assert any("maximum is 3" in e for e in errors)


# ------------------------------------------------------------------- Plan
def build_plan() -> Plan:
    tasks = [Task(**t.model_dump()) for t in GOOD_DRAFT.tasks]
    return Plan(goal="g", analysis=make_analysis(), strategy="s", tasks=tasks)


def test_plan_model_rejects_broken_graph() -> None:
    with pytest.raises(ValidationError, match="Circular dependency"):
        Plan(
            goal="g",
            analysis=make_analysis(),
            strategy="s",
            tasks=[Task(**task("t1", "web_search", ["t1"]).model_dump())],
        )


def test_ready_tasks_follow_dependencies() -> None:
    plan = build_plan()
    assert [t.id for t in plan.ready_tasks()] == ["t1", "t2"]

    plan.get_task("t1").status = TaskStatus.COMPLETED
    assert [t.id for t in plan.ready_tasks()] == ["t2"]  # t3 still waits for t2

    plan.get_task("t2").status = TaskStatus.COMPLETED
    assert [t.id for t in plan.ready_tasks()] == ["t3"]


def test_plan_is_finished_only_when_all_tasks_final() -> None:
    plan = build_plan()
    assert plan.is_finished is False

    for t in plan.tasks:
        t.status = TaskStatus.COMPLETED
    assert plan.is_finished is True


def test_plan_json_includes_computed_fields() -> None:
    data = build_plan().model_dump(mode="json")

    assert data["execution_order"] == ["t1", "t2", "t3", "t4", "t5"]
    assert data["parallel_groups"][0] == ["t1", "t2"]


@pytest.mark.anyio
async def test_planner_only_offers_available_tools(mock_llm) -> None:
    """With only some tools available, a plan using a missing tool is rejected and repaired."""
    from app.tools.catalog import TOOLS_BY_NAME

    available = [TOOLS_BY_NAME[n] for n in ("web_search", "llm_analysis", "generate_report")]
    planner = Planner.from_settings(mock_llm, tools=available)
    mock_llm.analyze_goal.return_value = make_analysis()
    mock_llm.structured.side_effect = [
        GOOD_DRAFT,  # uses save_to_database, which is NOT available here
        PlanDraft(strategy="s", tasks=[task("t1", "web_search"), task("t2", "generate_report", ["t1"])]),
    ]

    result = await planner.create_plan("Compare AI jobs")

    assert result.attempts == 2
    system_prompt = mock_llm.structured.await_args_list[0].args[0][0].content
    assert "save_to_database" not in system_prompt  # never even offered to the LLM
    repair = mock_llm.structured.await_args_list[1].args[0][-1].content
    assert "unknown tool 'save_to_database'" in repair
