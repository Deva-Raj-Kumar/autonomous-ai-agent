"""Approval records: a permanent audit trail of every sensitive action the agent asked for.

The pause/resume mechanics live in the LangGraph workflow (interrupt()). This module
stores WHAT was asked, WHO decided and WHEN, in your `approvals` table:

    approvals.task_id        -> the run's row in `tasks`
    approvals.step_key       -> which plan task ("t2")
    approvals.action_name    -> the tool ("send_email")
    approvals.action_details -> {"title": ..., "arguments": {...}}: EXACTLY what was shown
    approvals.arguments_hash -> SHA-256 fingerprint of those arguments
    approvals.approved_at    -> time of the decision (approved OR rejected)

    request()      - called when a run pauses: one PENDING record per waiting task
    decide()       - called when the human answers: records become APPROVED or REJECTED
    list_records() - for the dashboard's approval panel and for audits

request() is IDEMPOTENT: LangGraph re-runs the approval node from the top when a run
resumes, so the same request can arrive twice. An identical pending request (same run,
task and arguments fingerprint) is reused instead of duplicated.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.database.connection import Database
from app.database.crud import get_or_create_run
from app.database.models import AgentRun, ApprovalRecord
from app.timeutils import UTCDateTime


class ApprovalOut(BaseModel):
    id: int
    run_id: str
    task_id: str  # the plan task ("t2")
    tool: str
    title: str
    arguments: dict[str, Any]
    arguments_hash: str
    status: str
    requested_at: UTCDateTime | None
    decided_at: UTCDateTime | None
    decided_by: str | None


def fingerprint(arguments: dict[str, Any]) -> str:
    """SHA-256 of the arguments in a canonical form (sorted keys), so the same arguments
    always give the same fingerprint. Proves later exactly what was approved."""
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _to_out(record: ApprovalRecord, run_id: str) -> ApprovalOut:
    details = record.action_details or {}
    return ApprovalOut(
        id=record.id, run_id=run_id, task_id=record.step_key or "", tool=record.action_name or "",
        title=details.get("title", ""), arguments=details.get("arguments", {}),
        arguments_hash=record.arguments_hash or "", status=record.status or "pending",
        requested_at=record.requested_at, decided_at=record.approved_at, decided_by=record.decided_by,
    )


class ApprovalStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def request(self, run_id: str, task_id: str, tool: str, title: str, arguments: dict[str, Any]) -> ApprovalOut:
        return await asyncio.to_thread(self._request, run_id, task_id, tool, title, arguments)

    async def decide(self, run_id: str, approved_task_ids: set[str], decided_by: str) -> list[ApprovalOut]:
        """Close every PENDING record of the run: approved if listed, otherwise rejected."""
        return await asyncio.to_thread(self._decide, run_id, approved_task_ids, decided_by)

    # Not named `list`: that would shadow the built-in list type in the annotations below.
    async def list_records(
        self, *, status: str | None = None, run_id: str | None = None, limit: int = 100
    ) -> list[ApprovalOut]:
        return await asyncio.to_thread(self._list_records, status, run_id, limit)

    # ----------------------------------------------------- sync implementation
    def _request(self, run_id: str, task_id: str, tool: str, title: str, arguments: dict[str, Any]) -> ApprovalOut:
        digest = fingerprint(arguments)
        with self._db.session() as s:
            run = get_or_create_run(s, self._db, run_id)
            existing = s.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.task_id == run.id,
                    ApprovalRecord.step_key == task_id,
                    ApprovalRecord.arguments_hash == digest,
                    ApprovalRecord.status == "pending",
                )
            ).first()
            if existing is not None:  # resumed node asked again: reuse, don't duplicate
                return _to_out(existing, run_id)
            record = ApprovalRecord(
                task_id=run.id, step_key=task_id, action_name=tool,
                action_details={"title": title[:200], "arguments": arguments},
                arguments_hash=digest, status="pending",
            )
            s.add(record)
            s.flush()
            return _to_out(record, run_id)

    def _decide(self, run_id: str, approved_task_ids: set[str], decided_by: str) -> list[ApprovalOut]:
        now = datetime.now(UTC)
        with self._db.session() as s:
            run = s.scalars(
                select(AgentRun).where(AgentRun.run_id == run_id, AgentRun.user_id == self._db.current_user_id())
            ).first()
            if run is None:  # unknown, or not this user's run: nothing to decide
                return []
            pending = s.scalars(
                select(ApprovalRecord).where(ApprovalRecord.task_id == run.id, ApprovalRecord.status == "pending")
            ).all()
            for record in pending:
                record.status = "approved" if record.step_key in approved_task_ids else "rejected"
                record.approved_at, record.decided_by = now, decided_by[:100]
            return [_to_out(r, run_id) for r in pending]

    def _list_records(self, status: str | None, run_id: str | None, limit: int) -> list[ApprovalOut]:
        with self._db.session() as s:
            query = (
                select(ApprovalRecord, AgentRun.run_id)
                .join(AgentRun, ApprovalRecord.task_id == AgentRun.id)  # approvals -> tasks (the run)
                .where(AgentRun.user_id == self._db.current_user_id())
                .order_by(ApprovalRecord.id.desc())
            )
            if status:
                query = query.where(ApprovalRecord.status == status)
            if run_id:
                query = query.where(AgentRun.run_id == run_id)
            return [_to_out(record, rid or "") for record, rid in s.execute(query.limit(limit)).all()]
