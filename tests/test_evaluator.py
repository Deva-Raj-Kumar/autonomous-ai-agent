"""Evaluator tests: the LLM judge is a create_autospec(LLMService) mock; evidence and
decision logic run for real."""

import pytest

from app.agent.evaluator import (
    Evaluator,
    Verdict,
    _JudgeOutput,
    _JudgeTask,
    descendants,
    reset_for_retry,
)
from app.agent.executor import ArgumentBuilder
from app.agent.planner import Planner
from app.agent.schemas import Plan, TaskStatus
from app.llm.client import LLMError
from tests.test_executor import make_plan
from tests.test_planner import GOOD_DRAFT, make_analysis

pytestmark = pytest.mark.anyio


def completed_plan(outputs: dict[str, str], *specs: tuple) -> Plan:
    plan = make_plan(*specs)
    for task in plan.tasks:
        if task.id in outputs:
            task.status, task.result = TaskStatus.COMPLETED, outputs[task.id]
    return plan


def judge(*tasks: tuple, goal_achieved: bool = True, viable: bool = True) -> _JudgeOutput:
    """tasks: (task_id, passed, score, issues)"""
    return _JudgeOutput(
        tasks=[_JudgeTask(task_id=t, passed=p, score=s, issues=i, fix_hint="try harder" if i else "")
               for t, p, s, i in tasks],
        goal_achieved=goal_achieved, plan_is_viable=viable, summary="Overall summary.",
    )


SEARCH_AND_REPORT = (("t1", "web_search", []), ("t2", "generate_report", ["t1"]))


# ------------------------------------------------------------ decisions
async def test_all_good_is_accepted(mock_llm) -> None:
    plan = completed_plan({"t1": "393 jobs", "t2": "Report: 393 jobs"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(("t1", True, 9, []), ("t2", True, 8, []))

    ev = await Evaluator(mock_llm).evaluate(plan)

    assert ev.verdict == Verdict.ACCEPT and ev.reason == "All checks passed."
    assert ev.quality_score == 8.5 and ev.goal_achieved is True and ev.mode == "llm"
    assert mock_llm.structured.await_args.args[1] is _JudgeOutput


async def test_low_score_sends_task_back_with_reviewer_feedback(mock_llm) -> None:
    plan = completed_plan({"t1": "Hyderabad, Pakistan jobs", "t2": "Report"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(("t1", False, 1, ["wrong country"]), ("t2", True, 7, []))

    ev = await Evaluator(mock_llm, max_rounds=1).evaluate(plan, rounds_used=0)

    assert ev.verdict == Verdict.RETRY_TASKS and ev.retry_task_ids == ["t1"]
    assert ev.feedback["t1"] == "Reviewer: wrong country Hint: try harder"


async def test_unsupported_facts_send_the_report_back(mock_llm) -> None:
    plan = completed_plan({"t1": "393 jobs", "t2": "Report: 393 jobs and 2,500 internships"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(("t1", True, 9, []), ("t2", True, 7, []))  # judge missed it

    ev = await Evaluator(mock_llm).evaluate(plan)

    assert ev.verdict == Verdict.RETRY_TASKS and ev.retry_task_ids == ["t2"]
    assert "2,500" in ev.feedback["t2"]  # code caught what the LLM judge missed
    assert ev.evidence[0].unsupported == ["2,500"]
    judge_prompt = mock_llm.structured.await_args.args[0][-1].content
    assert "NOT found in sources: 2,500" in judge_prompt  # and the judge was told about it


async def test_unviable_plan_triggers_replan(mock_llm) -> None:
    plan = completed_plan({"t1": "nothing useful", "t2": "Report"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(
        ("t1", False, 2, ["wrong tool for this goal"]), goal_achieved=False, viable=False,
    )

    ev = await Evaluator(mock_llm, max_replans=1).evaluate(plan, replans_used=0)

    assert ev.verdict == Verdict.REPLAN
    assert "Overall summary." in ev.replan_feedback and "wrong tool" in ev.replan_feedback


async def test_replan_budget_falls_back_to_retry_then_accept(mock_llm) -> None:
    plan = completed_plan({"t1": "nothing", "t2": "Report"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(("t1", False, 2, ["bad"]), goal_achieved=False, viable=False)
    evaluator = Evaluator(mock_llm, max_replans=1, max_rounds=1)

    retry = await evaluator.evaluate(plan, replans_used=1, rounds_used=0)
    accept = await evaluator.evaluate(plan, replans_used=1, rounds_used=1)

    assert retry.verdict == Verdict.RETRY_TASKS
    assert accept.verdict == Verdict.ACCEPT and "Retry rounds used up" in accept.reason
    assert any("NOT fully achieved" in issue for issue in accept.open_issues)


async def test_judge_output_is_validated_in_code(mock_llm) -> None:
    plan = completed_plan({"t1": "393 jobs", "t2": "Report: 393"}, *SEARCH_AND_REPORT)
    mock_llm.structured.return_value = judge(
        ("t1", True, 99, []),  # out-of-range score
        ("t9", False, 0, ["made-up task"]),  # unknown id
        ("t2", True, 7, []),
    )

    ev = await Evaluator(mock_llm).evaluate(plan)

    assert [(j.task_id, j.score) for j in ev.task_judgements] == [("t1", 10), ("t2", 7)]
    assert ev.verdict == Verdict.ACCEPT  # the fake t9 complaint changed nothing


async def test_judge_failure_falls_back_to_rules(mock_llm) -> None:
    plan = completed_plan({"t2": "Report"}, *SEARCH_AND_REPORT)
    plan.get_task("t1").status, plan.get_task("t1").error = TaskStatus.FAILED, "timeout"
    mock_llm.structured.side_effect = LLMError("judge overloaded")

    ev = await Evaluator(mock_llm).evaluate(plan)

    assert ev.mode == "rules" and "judge overloaded" in ev.judge_error
    assert ev.verdict == Verdict.RETRY_TASKS and ev.retry_task_ids == ["t1"]


async def test_rules_mode_never_calls_the_llm(mock_llm) -> None:
    plan = completed_plan({"t1": "393", "t2": "Report 393"}, *SEARCH_AND_REPORT)

    ev = await Evaluator(mock_llm, mode="rules").evaluate(plan)

    assert ev.verdict == Verdict.ACCEPT
    mock_llm.structured.assert_not_awaited()


async def test_unfixable_failures_are_open_issues_not_retries(mock_llm) -> None:
    plan = completed_plan({"t1": "393"}, ("t1", "web_search", []), ("t2", "send_email", []))
    plan.get_task("t2").status, plan.get_task("t2").error = TaskStatus.FAILED, "Tool 'send_email' is not available."
    mock_llm.structured.return_value = judge(("t1", True, 9, []))

    ev = await Evaluator(mock_llm).evaluate(plan)

    assert ev.verdict == Verdict.ACCEPT and ev.retry_task_ids == []
    assert ev.open_issues == ["t2 failed: Tool 'send_email' is not available."]


# --------------------------------------------------------------- retries
def test_reset_for_retry_resets_descendants_and_attaches_feedback() -> None:
    plan = completed_plan(
        {"t1": "old search", "t2": "old analysis", "t3": "old report", "t5": "independent"},
        ("t1", "web_search", []), ("t2", "llm_analysis", ["t1"]), ("t3", "generate_report", ["t2"]),
        ("t4", "send_email", []), ("t5", "calculator", []),
    )
    plan.get_task("t4").status, plan.get_task("t4").error = TaskStatus.SKIPPED, "Rejected by the user."

    reset_for_retry(plan, ["t1"], {"t1": "add India to the query"})

    t1, t2, t3, t4, t5 = (plan.get_task(i) for i in ("t1", "t2", "t3", "t4", "t5"))
    assert (t1.status, t1.result, t1.feedback) == (TaskStatus.PENDING, None, "add India to the query")
    assert t2.status == t3.status == TaskStatus.PENDING and t2.result is None  # inputs will change
    assert t4.status == TaskStatus.SKIPPED  # user rejections are never undone
    assert t5.status == TaskStatus.COMPLETED and t5.result == "independent"  # untouched
    assert descendants(plan, {"t1"}) == {"t2", "t3"}


def test_feedback_reaches_the_next_attempt(mock_llm) -> None:
    plan = make_plan(("t1", "generate_report", []))
    plan.get_task("t1").feedback = "Remove the number 2,500."

    fields = ArgumentBuilder.auto_fields(plan.get_task("t1"), dependency_results="data")

    assert "A reviewer rejected the previous version" in fields["instructions"]
    assert "Remove the number 2,500." in fields["instructions"]


async def test_planner_receives_replan_feedback(mock_llm) -> None:
    mock_llm.analyze_goal.return_value = make_analysis()
    mock_llm.structured.return_value = GOOD_DRAFT

    await Planner(mock_llm).create_plan("goal", feedback="web_search found nothing; use the knowledge base")

    human = mock_llm.structured.await_args.args[0][-1].content
    assert "did NOT work" in human and "use the knowledge base" in human
