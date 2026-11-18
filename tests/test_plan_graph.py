"""Unit tests for the task-graph algorithms (pure functions, no LLM)."""

import pytest

from app.agent.plan_graph import (
    compute_execution_order,
    compute_parallel_groups,
    find_graph_errors,
)
from app.agent.schemas import PlannedTask


def t(task_id: str, deps: list[str] | None = None, priority: str = "medium") -> PlannedTask:
    """Tiny helper to build a task with only the fields the graph cares about."""
    return PlannedTask(
        id=task_id,
        title=f"Task {task_id}",
        description="do it",
        tool="llm_analysis",
        depends_on=deps or [],
        priority=priority,
        expected_output="done",
    )


# The plan from the README: two parallel searches, then analysis, report, save.
JOB_PLAN = [
    t("t1"),
    t("t2"),
    t("t3", ["t1", "t2"]),
    t("t4", ["t3"]),
    t("t5", ["t4"]),
]


def test_valid_graph_has_no_errors() -> None:
    assert find_graph_errors(JOB_PLAN) == []


def test_execution_order_respects_dependencies() -> None:
    order = compute_execution_order(JOB_PLAN)

    assert order == ["t1", "t2", "t3", "t4", "t5"]
    for task in JOB_PLAN:
        for dep in task.depends_on:
            assert order.index(dep) < order.index(task.id)


def test_parallel_groups() -> None:
    assert compute_parallel_groups(JOB_PLAN) == [["t1", "t2"], ["t3"], ["t4"], ["t5"]]


def test_priority_breaks_ties_between_ready_tasks() -> None:
    tasks = [t("t1", priority="low"), t("t2", priority="high"), t("t3", priority="medium")]

    assert compute_execution_order(tasks) == ["t2", "t3", "t1"]


def test_dependencies_beat_priority() -> None:
    # t2 is high priority but needs t1, so t1 must still run first.
    tasks = [t("t1", priority="low"), t("t2", ["t1"], priority="high")]

    assert compute_execution_order(tasks) == ["t1", "t2"]


def test_empty_plan_is_invalid() -> None:
    assert find_graph_errors([]) == ["The plan has no tasks."]


def test_unknown_dependency_detected() -> None:
    errors = find_graph_errors([t("t1", ["t9"])])

    assert any("unknown task 't9'" in e for e in errors)


def test_self_dependency_detected() -> None:
    errors = find_graph_errors([t("t1", ["t1"])])

    assert any("depends on itself" in e for e in errors)


def test_duplicate_ids_detected() -> None:
    errors = find_graph_errors([t("t1"), t("t1")])

    assert any("Duplicate task ids: t1" in e for e in errors)


def test_cycle_detected_and_named() -> None:
    # t1 -> t2 -> t3 -> t1 is a loop; t4 is fine.
    tasks = [t("t1", ["t3"]), t("t2", ["t1"]), t("t3", ["t2"]), t("t4")]

    errors = find_graph_errors(tasks)

    assert errors == ["Circular dependency between tasks: t1, t2, t3."]


def test_execution_order_raises_on_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        compute_execution_order([t("t1", ["t2"]), t("t2", ["t1"])])
