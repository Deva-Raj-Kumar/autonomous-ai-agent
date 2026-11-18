"""Task and plan schemas.

Two layers, on purpose:
  1. LLM-facing schemas (PlannedTask, PlanDraft): only what the model should decide.
     Small and simple, so the model fills them in reliably.
  2. Domain models (Task, Plan): what our program works with. They add fields the LLM
     must NOT control (status, attempts, requires_approval) and they validate themselves.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, model_validator

from app.agent.plan_graph import compute_execution_order, compute_parallel_groups, find_graph_errors
from app.llm.schemas import GoalAnalysis

Priority = Literal["high", "medium", "low"]


class TaskStatus(StrEnum):
    """Lifecycle of a task. StrEnum values behave like strings ("pending") in JSON and the DB."""

    PENDING = "pending"  # not started yet
    RUNNING = "running"  # executor is working on it (Phase 7)
    WAITING_APPROVAL = "waiting_approval"  # paused until a human approves (Phase 10)
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # e.g. a dependency failed, or the human rejected it


# ---------------------------------------------------------------- LLM-facing
class PlannedTask(BaseModel):
    """One task as proposed by the LLM. Field descriptions are instructions to the model."""

    id: str = Field(description="Short unique id: 't1', 't2', 't3', ... in listing order.")
    title: str = Field(description="Short imperative title, at most about 8 words.")
    description: str = Field(
        description="Exactly what to do. Self-contained: include the names, places and "
        "numbers from the goal so it can be executed without reading the goal."
    )
    tool: str = Field(description="Name of exactly ONE tool from the available tools list.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Ids of earlier tasks whose RESULTS this task needs. Empty if none.",
    )
    priority: Priority = Field(
        description="high = on the critical path to the main deliverable; "
        "medium = needed but can wait; low = nice to have."
    )
    expected_output: str = Field(
        description="What a correct, complete result of this task looks like (used to verify it)."
    )


class PlanDraft(BaseModel):
    """The LLM's whole proposed plan."""

    # `strategy` comes FIRST: the model writes its reasoning before listing tasks,
    # which tends to produce better-structured plans.
    strategy: str = Field(description="2-3 sentences explaining the approach of this plan.")
    tasks: list[PlannedTask] = Field(description="The tasks, in a sensible execution order.")


# ------------------------------------------------------------------ domain
class Task(PlannedTask):
    """A task inside a validated plan. Adds fields controlled only by our code."""

    requires_approval: bool = False  # set from the tool catalog, never by the LLM
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    result: str | None = None
    error: str | None = None
    # Set by the evaluator when it sends a task back: what was wrong last time.
    # The executor shows it to the LLM on the next attempt.
    feedback: str | None = None
    # For tasks that need approval: the EXACT arguments generated BEFORE the pause and
    # shown to the human. After approval, precisely these run (never regenerated).
    proposed_arguments: dict | None = None


class Plan(BaseModel):
    """A validated, executable plan. It cannot be created with a broken task graph."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str
    analysis: GoalAnalysis
    strategy: str
    tasks: list[Task]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _check_task_graph(self) -> "Plan":
        """Runs after the fields are validated. Rejects duplicate ids, missing deps, cycles."""
        errors = find_graph_errors(self.tasks)
        if errors:
            raise ValueError("Invalid task graph: " + "; ".join(errors))
        return self

    # @computed_field: computed from `tasks` every time, AND included in JSON output.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def execution_order(self) -> list[str]:
        """One valid order to run the tasks one by one."""
        return compute_execution_order(self.tasks)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def parallel_groups(self) -> list[list[str]]:
        """Waves of tasks. Tasks in the same wave don't depend on each other."""
        return compute_parallel_groups(self.tasks)

    def get_task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"No task with id {task_id!r}")

    def ready_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies are all completed: what can run next (Phase 7)."""
        done = {t.id for t in self.tasks if t.status == TaskStatus.COMPLETED}
        position = {task_id: i for i, task_id in enumerate(self.execution_order)}
        ready = [
            t
            for t in self.tasks
            if t.status == TaskStatus.PENDING and all(dep in done for dep in t.depends_on)
        ]
        return sorted(ready, key=lambda t: position[t.id])

    @property
    def is_finished(self) -> bool:
        """True when no task is pending, running or waiting."""
        final = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}
        return all(t.status in final for t in self.tasks)


class PlanningResult(BaseModel):
    """What the planner returns: either a plan, or questions for the user."""

    status: Literal["planned", "needs_clarification"]
    analysis: GoalAnalysis
    plan: Plan | None = None
    clarifying_questions: list[str] = Field(default_factory=list)
    attempts: int = Field(description="LLM drafting attempts used (0 if no plan was drafted).")


# ------------------------------------------------------- execution (Phase 7)
class ExecutionStatus(StrEnum):
    COMPLETED = "completed"  # every task completed
    PARTIAL = "partial"  # some tasks completed, some failed or were skipped
    FAILED = "failed"  # nothing useful completed
    WAITING_APPROVAL = "waiting_approval"  # paused: a task needs a human's approval
    STOPPED = "stopped"  # a safety limit (steps or time) ended the run


class TaskRunRecord(BaseModel):
    """One attempt at one task: the audit trail of what the agent actually did."""

    task_id: str
    attempt: int
    tool: str
    arguments: dict = Field(default_factory=dict)  # long values are shortened for the log
    status: str  # the ToolStatus value, or "error" if arguments couldn't be built
    output_preview: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    security_flags: list[str] = Field(default_factory=list)  # possible prompt injection found
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionEvent(BaseModel):
    """Progress notification (CLI progress today, live dashboard updates in Phase 13)."""

    kind: Literal["run_started", "task_started", "task_finished", "task_skipped", "run_finished"]
    task_id: str | None = None
    message: str = ""


class ExecutionResult(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str
    status: ExecutionStatus
    plan: Plan  # with final task statuses and results
    final_output: str | None = Field(default=None, description="The report / answer for the user.")
    records: list[TaskRunRecord] = Field(default_factory=list)
    steps_used: int = 0
    duration_ms: float = 0.0
    pending_approvals: list[str] = Field(default_factory=list, description="Task ids waiting for approval.")
    stop_reason: str | None = None
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
