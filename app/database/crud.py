"""CRUD for agent-run history: your `tasks`, `task_steps` and `tool_logs` tables.

CRUD = Create, Read, Update, Delete: the basic database operations.

Two kinds of storage, two jobs:
  - LangGraph CHECKPOINTS (data/checkpoints.db): the workflow's execution state, so a run
    can pause and resume. Internal, replaced on every step.
  - These TABLES: the permanent, queryable HISTORY: which runs happened, their plans,
    every tool call with inputs, outputs and timing. For audits, the dashboard and analytics
    ("which tool fails most?", "average steps per run?").

The workflow calls this repository after each step. History must never break a run, so
the workflow logs repository errors instead of raising them.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.schemas import Plan
from app.database.connection import Database
from app.database.models import AgentRun, RunStep, ToolLog
from app.timeutils import UTCDateTime

MAX_STORED_RESULT_CHARS = 20_000  # one step's result in task_steps.result (JSON)


class RunSummaryRow(BaseModel):
    run_id: str
    goal: str
    status: str | None
    steps_used: int
    quality_score: float | None
    created_at: UTCDateTime | None
    updated_at: UTCDateTime | None


class StepRow(BaseModel):
    step_number: int
    step_key: str | None
    title: str | None
    tool_name: str | None
    status: str | None
    attempts: int
    error: str | None
    result: dict | None


class ToolLogRow(BaseModel):
    step_key: str | None
    attempt: int
    tool_name: str | None
    status: str | None
    execution_time_ms: int | None
    input_data: dict | None
    output_data: dict | None
    error: str | None
    created_at: UTCDateTime | None


class RunHistory(BaseModel):
    run: RunSummaryRow
    final_output: str | None
    error: str | None
    steps: list[StepRow]
    tool_logs: list[ToolLogRow]


def get_or_create_run(s: Session, database: Database, run_id: str, goal: str = "") -> AgentRun:
    """The AgentRun row for a LangGraph run id (created if missing)."""
    run = s.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).first()
    if run is None:
        run = AgentRun(user_id=database.current_user_id(), run_id=run_id, goal=goal or "(unknown goal)",
                       status="planning")
        s.add(run)
        s.flush()
    return run


def _summary(run: AgentRun) -> RunSummaryRow:
    return RunSummaryRow(
        run_id=run.run_id or "", goal=run.goal, status=run.status, steps_used=run.steps_used,
        quality_score=run.quality_score, created_at=run.created_at, updated_at=run.updated_at,
    )


class RunRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create_run(self, run_id: str, goal: str) -> None:
        await asyncio.to_thread(self._create_run, run_id, goal)

    async def sync_plan(self, run_id: str, plan: Plan) -> None:
        """Insert or update one task_steps row per plan task (idempotent: safe to repeat)."""
        await asyncio.to_thread(self._sync_plan, run_id, plan)

    async def add_tool_logs(self, run_id: str, records: list[dict[str, Any]]) -> None:
        if records:
            await asyncio.to_thread(self._add_tool_logs, run_id, records)

    async def update_run(self, run_id: str, **fields: Any) -> None:
        """Update status / steps_used / final_output / quality_score / error."""
        await asyncio.to_thread(self._update_run, run_id, fields)

    async def list_runs(self, limit: int = 20) -> list[RunSummaryRow]:
        return await asyncio.to_thread(self._list_runs, limit)

    async def history(self, run_id: str) -> RunHistory | None:
        return await asyncio.to_thread(self._history, run_id)

    async def is_mine(self, run_id: str) -> bool:
        """Does the current user own this run? (The tasks row is the ownership record.)"""
        return await asyncio.to_thread(self._is_mine, run_id)

    # ----------------------------------------------------- sync implementation
    def _mine(self):
        return select(AgentRun).where(AgentRun.user_id == self._db.current_user_id())

    def _is_mine(self, run_id: str) -> bool:
        with self._db.session() as s:
            return s.scalar(self._mine().with_only_columns(AgentRun.id).where(AgentRun.run_id == run_id)) is not None

    def _create_run(self, run_id: str, goal: str) -> None:
        with self._db.session() as s:
            run = get_or_create_run(s, self._db, run_id, goal)
            run.goal = goal

    def _sync_plan(self, run_id: str, plan: Plan) -> None:
        with self._db.session() as s:
            run = get_or_create_run(s, self._db, run_id, plan.goal)
            existing = {step.step_key: step for step in s.scalars(select(RunStep).where(RunStep.task_id == run.id))}
            keep = {task.id for task in plan.tasks}
            for stale_key in set(existing) - keep:  # a RE-plan replaces the old steps
                s.delete(existing.pop(stale_key))
            # (task_id, step_number) is UNIQUE, and MySQL checks it after EVERY statement.
            # Renumbering in place (t1: 1->2 while t2 still has 2) would collide, so park the
            # existing rows on temporary negative numbers first.
            for i, step in enumerate(existing.values(), start=1):
                step.step_number = -i
            s.flush()
            for number, task_id in enumerate(plan.execution_order, start=1):
                task = plan.get_task(task_id)
                step = existing.get(task.id)
                if step is None:
                    step = RunStep(task_id=run.id, step_key=task.id)
                    s.add(step)
                result = None
                if task.result is not None or task.feedback:
                    result = {"output": (task.result or "")[:MAX_STORED_RESULT_CHARS], "feedback": task.feedback}
                step.step_number, step.title, step.description = number, task.title[:200], task.description
                step.tool_name, step.status, step.attempts = task.tool, task.status.value, task.attempts
                step.error, step.result = task.error, result
            run.updated_at = datetime.now(UTC)

    def _add_tool_logs(self, run_id: str, records: list[dict[str, Any]]) -> None:
        with self._db.session() as s:
            run = get_or_create_run(s, self._db, run_id)
            # The executor counts attempts per round (1, 2, 3), and an evaluator retry starts a
            # new round at 1 again. Stored attempts continue from the step's highest so far, so
            # history reads t2 #1, t2 #2 instead of two confusing "#1" rows.
            previous = dict(s.execute(
                select(ToolLog.step_key, func.max(ToolLog.attempt))
                .where(ToolLog.task_id == run.id).group_by(ToolLog.step_key)
            ).all())
            offsets = {key: previous.get(key) or 0 for key in {r.get("task_id") for r in records}}
            for record in records:
                s.add(ToolLog(
                    task_id=run.id,
                    step_key=record.get("task_id"),
                    attempt=offsets[record.get("task_id")] + record.get("attempt", 1),
                    tool_name=record.get("tool"),
                    input_data=record.get("arguments") or {},
                    output_data={"preview": record.get("output_preview", ""),
                                 "security_flags": record.get("security_flags", [])},
                    status=record.get("status"),
                    execution_time_ms=int(record.get("duration_ms") or 0),
                    error=record.get("error"),
                ))

    def _update_run(self, run_id: str, fields: dict[str, Any]) -> None:
        allowed = {"status", "steps_used", "final_output", "quality_score", "error", "goal"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown run fields: {sorted(unknown)}")
        with self._db.session() as s:
            run = get_or_create_run(s, self._db, run_id)
            for name, value in fields.items():
                setattr(run, name, value)
            run.updated_at = datetime.now(UTC)

    def _list_runs(self, limit: int) -> list[RunSummaryRow]:
        with self._db.session() as s:
            runs = s.scalars(
                self._mine()
                .where(AgentRun.run_id.is_not(None))
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(limit)
            ).all()
            return [_summary(r) for r in runs]

    def _history(self, run_id: str) -> RunHistory | None:
        with self._db.session() as s:
            run = s.scalars(self._mine().where(AgentRun.run_id == run_id)).first()
            if run is None:  # missing OR someone else's: the same answer
                return None
            steps = s.scalars(select(RunStep).where(RunStep.task_id == run.id).order_by(RunStep.step_number)).all()
            logs = s.scalars(select(ToolLog).where(ToolLog.task_id == run.id).order_by(ToolLog.id)).all()
            return RunHistory(
                run=_summary(run), final_output=run.final_output, error=run.error,
                steps=[StepRow(step_number=x.step_number, step_key=x.step_key, title=x.title, tool_name=x.tool_name,
                               status=x.status, attempts=x.attempts, error=x.error, result=x.result) for x in steps],
                tool_logs=[ToolLogRow(step_key=x.step_key, attempt=x.attempt, tool_name=x.tool_name, status=x.status,
                                      execution_time_ms=x.execution_time_ms, input_data=x.input_data,
                                      output_data=x.output_data, error=x.error, created_at=x.created_at)
                           for x in logs],
            )
