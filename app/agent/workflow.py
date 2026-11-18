r"""LangGraph workflow: the agent as a state machine with persistent checkpoints.

    START -> plan --(unclear/error)--------------------------------------> END
             ^ (evaluator: plan can't work -> REPLAN with feedback, bounded)
               \-> execute <-----------+      ONE wave per visit: a checkpoint after each
                     |  more ready ----+
                     |-- needs approval -> approval --interrupt()-- (paused) --> execute
                     |-- limit hit -------------------------------> finalize
                     \-- nothing left -> evaluate --retry--> execute
                                                \--accept--> finalize -> END

Key LangGraph ideas used here:
  - STATE:       a TypedDict passed between nodes. Each node returns only the keys it
                 changes; LangGraph merges them in. `records` uses a reducer
                 (operator.add), so node updates are APPENDED, not overwritten.
  - NODES:       async functions state -> partial state update.
  - EDGES:       fixed (A always goes to B) or conditional (a router function looks at
                 the state and picks the next node).
  - CHECKPOINTS: after every node, the whole state is saved under the run's thread_id
                 (SQLite here). A crash loses at most the node that was running.
  - interrupt(): pauses the graph inside a node and saves it. The run resumes, minutes
                 or days later, even after a restart, with Command(resume=answer).

The state holds plain JSON (dicts/lists/str), not Pydantic objects: checkpoints stay
readable, portable and safe to deserialize. Nodes rebuild Plan objects as needed.
"""

import asyncio
import logging
import operator
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agent.evaluator import Evaluator, Verdict, reset_for_retry
from app.agent.executor import EventCallback, TaskExecutor
from app.agent.planner import Planner
from app.agent.schemas import Plan, TaskStatus
from app.config import Settings
from app.database.crud import RunRepository
from app.llm.client import LLMError
from app.llm.service import LLMService
from app.safety.approval import ApprovalStore
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class RunStatus(StrEnum):
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"
    NEEDS_CLARIFICATION = "needs_clarification"
    ERROR = "error"


FINISHED = {
    RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.STOPPED,
    RunStatus.NEEDS_CLARIFICATION, RunStatus.ERROR,
}


class AgentState(TypedDict, total=False):
    run_id: str
    goal: str
    status: str
    created_at: str
    planning: dict | None  # PlanningResult as JSON (includes clarifying questions)
    plan: dict | None  # Plan as JSON: task statuses and results live here
    records: Annotated[list[dict], operator.add]  # reducer: every node's records are APPENDED
    steps_used: int
    approved_task_ids: list[str]
    evaluation_rounds: int  # retry rounds used for the CURRENT plan
    evaluation: dict | None  # the latest evaluation
    evaluation_history: Annotated[list[dict], operator.add]  # every evaluation, appended
    replans: int
    replan_feedback: str | None  # why the last plan failed (input for the next plan)
    final_output: str | None
    stop_reason: str | None
    error: str | None


class ApprovalDecision(BaseModel):
    """The human's answer when a run is waiting. Tasks NOT approved are rejected
    (default deny: silence never means yes)."""

    approved: list[str] = Field(default_factory=list, description="Task ids the human approves.")
    # Who decided, for the audit trail. Set by the API/CLI (Phase 12 uses the logged-in user).
    decided_by: str = Field(default="user", max_length=100)


class RunView(BaseModel):
    """A run as seen from outside: built from the latest checkpoint."""

    run_id: str
    goal: str
    status: str
    created_at: str = ""
    running: bool = Field(description="True while a background worker is executing this run.")
    resumable: bool = Field(default=False, description="Interrupted mid-run; can be continued.")
    next_nodes: list[str] = Field(description="Where the graph continues (empty = finished).")
    plan: dict | None = None
    planning: dict | None = None
    records: list[dict] = Field(default_factory=list)
    steps_used: int = 0
    pending_approvals: list[dict] = Field(default_factory=list)
    evaluation: dict | None = None
    evaluation_history: list[dict] = Field(default_factory=list)
    replans: int = 0
    final_output: str | None = None
    stop_reason: str | None = None
    error: str | None = None


def verification_notes(evaluation: dict | None) -> str:
    """A Markdown section listing what the evaluator could NOT verify (empty if all good)."""
    if not evaluation or not evaluation.get("open_issues"):
        return ""
    lines = ["", "", "---", "## Verification notes (automatic)"]
    if evaluation.get("quality_score") is not None:
        lines.append(f"Reviewer quality score: {evaluation['quality_score']}/10")
    lines += [f"- {issue}" for issue in evaluation["open_issues"]]
    return "\n".join(lines) + "\n"


class AgentWorkflow:
    def __init__(
        self,
        *,
        llm_factory: Callable[[], LLMService],
        registry: ToolRegistry,
        settings: Settings,
        checkpointer: Any,
        on_event: EventCallback | None = None,
        approval_store: ApprovalStore | None = None,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._llm: LLMService | None = None
        self._registry = registry
        self._settings = settings
        self._on_event = on_event
        self._approvals = approval_store  # audit trail in the database (None = not recorded)
        self._history = run_repository  # run history tables (None = not recorded)
        self._background: dict[str, asyncio.Task] = {}  # run_id -> running worker
        self._crashes: dict[str, str] = {}  # run_id -> last worker crash (since process start)
        self._starting: dict[str, str] = {}  # run_id -> goal, until its first checkpoint exists
        self.checkpointer = checkpointer
        self.graph = self._build_graph().compile(checkpointer=checkpointer)

    # ------------------------------------------------------------ the graph
    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)
        # Every node is wrapped so its changes are also written to the history tables.
        graph.add_node("plan", self._recorded(self._plan))
        graph.add_node("execute", self._recorded(self._execute))
        graph.add_node("approval", self._recorded(self._approval))
        graph.add_node("evaluate", self._recorded(self._evaluate))
        graph.add_node("finalize", self._recorded(self._finalize))

        graph.add_edge(START, "plan")
        # Conditional edges: the router's return value is the name of the next node.
        graph.add_conditional_edges("plan", self._after_plan, ["execute", END])
        graph.add_conditional_edges("execute", self._after_execute, ["execute", "approval", "evaluate", "finalize"])
        graph.add_edge("approval", "execute")
        graph.add_conditional_edges("evaluate", self._after_evaluate, ["execute", "plan", "finalize"])
        graph.add_edge("finalize", END)
        return graph

    @property
    def llm(self) -> LLMService:
        if self._llm is None:
            self._llm = self._llm_factory()
        return self._llm

    def _executor(self, approved: list[str], run_id: str | None = None) -> TaskExecutor:
        return TaskExecutor.from_settings(
            self._registry, self.llm, self._settings,
            approved_task_ids=frozenset(approved), on_event=self._on_event, run_id=run_id,
        )

    # --------------------------------------------------------- run history (Phase 11)
    def _recorded(self, node: Callable):
        """Wrap a node: run it, then save what it changed to the history tables.
        (If the node pauses with interrupt(), nothing is saved here: the execute node
        before it already recorded the waiting status.)"""

        async def wrapped(state: AgentState) -> dict:
            update = await node(state)
            await self._save_history(state["run_id"], update)
            return update

        wrapped.__name__ = node.__name__
        return wrapped

    async def _save_history(self, run_id: str, update: dict) -> None:
        if self._history is None:
            return
        try:
            if update.get("plan"):
                await self._history.sync_plan(run_id, Plan.model_validate(update["plan"]))
            await self._history.add_tool_logs(run_id, update.get("records") or [])
            fields = {k: update[k] for k in ("status", "steps_used", "final_output", "error") if k in update}
            evaluation = update.get("evaluation") or {}
            if evaluation.get("quality_score") is not None:
                fields["quality_score"] = evaluation["quality_score"]
            if fields:
                await self._history.update_run(run_id, **fields)
        except Exception as exc:  # history must never break a run; the checkpoint has the real state
            logger.warning("Run %s: could not save history (%s: %s)", run_id[:8], type(exc).__name__, exc)

    # ---------------------------------------------------------------- nodes
    async def _plan(self, state: AgentState) -> dict:
        planner = Planner.from_settings(self.llm, self._settings, tools=self._registry.available_specs())
        feedback = state.get("replan_feedback")  # set when the evaluator asked for a NEW plan
        try:
            planning = await planner.create_plan(state["goal"], feedback=feedback)
        except LLMError as exc:  # becomes a visible run status, not a crashed worker
            return {"status": RunStatus.ERROR.value, "error": f"Planning failed: {exc}"}
        if planning.status != "planned" or planning.plan is None:
            return {"status": RunStatus.NEEDS_CLARIFICATION.value, "planning": planning.model_dump(mode="json")}
        return {
            "status": RunStatus.EXECUTING.value,
            "planning": planning.model_dump(mode="json"),
            "plan": planning.plan.model_dump(mode="json"),
            # A new plan has NEW task ids: earlier approvals must not carry over to it.
            "approved_task_ids": [],
            "evaluation_rounds": 0,
            "replan_feedback": None,
        }

    async def _execute(self, state: AgentState) -> dict:
        plan = Plan.model_validate(state["plan"])
        result = await self._executor(state.get("approved_task_ids", []), state["run_id"]).execute(
            plan, steps_used=state.get("steps_used", 0), max_waves=1, produce_final_output=False
        )
        waiting = any(t.status == TaskStatus.WAITING_APPROVAL for t in result.plan.tasks)
        return {
            "plan": result.plan.model_dump(mode="json"),
            "records": [r.model_dump(mode="json") for r in result.records],
            "steps_used": result.steps_used,
            "stop_reason": result.stop_reason,
            "status": (RunStatus.WAITING_APPROVAL if waiting else RunStatus.EXECUTING).value,
        }

    async def _approval(self, state: AgentState) -> dict:
        plan = Plan.model_validate(state["plan"])
        run_id = state["run_id"]
        waiting = [t for t in plan.tasks if t.status == TaskStatus.WAITING_APPROVAL]
        # Audit trail: record each request (idempotent, because this node runs again on resume).
        if self._approvals is not None:
            for t in waiting:
                await self._approvals.request(run_id, t.id, t.tool, t.title, t.proposed_arguments or {})
        # interrupt() saves a checkpoint and STOPS here. When the run is resumed with
        # Command(resume=...), this node runs again from the top and interrupt()
        # returns the human's answer instead of pausing.
        answer = interrupt(
            {
                "type": "approval",
                "tasks": [
                    {
                        "id": t.id, "title": t.title, "tool": t.tool, "description": t.description,
                        # APPROVE WHAT YOU SEE: the exact code / recipients / body that will run.
                        "arguments": t.proposed_arguments,
                    }
                    for t in waiting
                ],
            }
        )
        decision = ApprovalDecision.model_validate(answer)  # never trust the payload shape
        approved = {t.id for t in waiting} & set(decision.approved)
        for task in waiting:
            if task.id in approved:
                task.status = TaskStatus.PENDING
            else:
                task.status, task.error = TaskStatus.SKIPPED, "Rejected by the user."
        if self._approvals is not None:
            await self._approvals.decide(run_id, approved, decision.decided_by)
        logger.info("Run %s approval by %s: approved=%s", run_id[:8], decision.decided_by, sorted(approved))
        return {
            "plan": plan.model_dump(mode="json"),
            "approved_task_ids": sorted(set(state.get("approved_task_ids", [])) | approved),
            "status": RunStatus.EXECUTING.value,
        }

    async def _evaluate(self, state: AgentState) -> dict:
        plan = Plan.model_validate(state["plan"])
        rounds = state.get("evaluation_rounds", 0)
        replans = state.get("replans", 0)
        judge_llm = self.llm if self._settings.evaluation_mode == "llm" else None
        evaluation = await Evaluator.from_settings(judge_llm, self._settings).evaluate(
            plan, rounds_used=rounds, replans_used=replans
        )
        logger.info("Run %s evaluation: %s (%s)", state["run_id"][:8], evaluation.verdict.value, evaluation.reason)
        record = evaluation.model_dump(mode="json")
        update: dict = {"evaluation": record, "evaluation_history": [record]}
        if evaluation.verdict == Verdict.RETRY_TASKS:
            reset_for_retry(plan, evaluation.retry_task_ids, evaluation.feedback)
            # An approval covered ONE specific action. Retried tasks will generate new
            # arguments, so their old approvals are revoked: they must be approved again.
            still_approved = set(state.get("approved_task_ids", [])) - set(evaluation.retry_task_ids)
            update |= {
                "plan": plan.model_dump(mode="json"),
                "evaluation_rounds": rounds + 1,
                "approved_task_ids": sorted(still_approved),
            }
        elif evaluation.verdict == Verdict.REPLAN:
            update |= {"replan_feedback": evaluation.replan_feedback, "replans": replans + 1}
        return update

    async def _finalize(self, state: AgentState) -> dict:
        plan = Plan.model_validate(state["plan"])
        execution_status = TaskExecutor.final_status(plan, state.get("stop_reason"))
        final_output = await self._executor([]).compose_final_output(plan)
        notes = verification_notes(state.get("evaluation"))
        if final_output and notes:
            final_output += notes  # be honest about what could not be verified
        return {"status": RunStatus(execution_status.value).value, "final_output": final_output}

    # -------------------------------------------------------------- routers
    @staticmethod
    def _after_plan(state: AgentState) -> str:
        return "execute" if state.get("status") == RunStatus.EXECUTING else END

    @staticmethod
    def _after_execute(state: AgentState) -> str:
        plan = Plan.model_validate(state["plan"])
        if state.get("stop_reason"):
            return "finalize"
        if plan.ready_tasks():  # independent work first, before pausing for a human
            return "execute"
        if any(t.status == TaskStatus.WAITING_APPROVAL for t in plan.tasks):
            return "approval"
        return "evaluate"

    @staticmethod
    def _after_evaluate(state: AgentState) -> str:
        verdict = (state.get("evaluation") or {}).get("verdict")
        if verdict == Verdict.RETRY_TASKS:
            return "execute"
        if verdict == Verdict.REPLAN:
            return "plan"
        return "finalize"

    # ------------------------------------------------------------ public API
    def _config(self, run_id: str) -> dict:
        # thread_id = which run's checkpoints to load/save.
        return {"configurable": {"thread_id": run_id}, "recursion_limit": self._settings.graph_recursion_limit}

    async def start(self, goal: str, run_id: str | None = None, *, row_created: bool = False) -> str:
        """Run a new goal until it finishes or pauses. Returns the run id."""
        run_id = run_id or uuid4().hex
        initial: AgentState = {
            "run_id": run_id, "goal": goal, "status": RunStatus.PLANNING.value,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "records": [], "steps_used": 0, "approved_task_ids": [], "evaluation_rounds": 0,
            "evaluation_history": [], "replans": 0,
        }
        if not row_created:
            await self._create_row(run_id, goal)
        await self.graph.ainvoke(initial, self._config(run_id))
        return run_id

    async def _create_row(self, run_id: str, goal: str) -> None:
        """The tasks row is the run's OWNERSHIP record (Phase 12), so unlike the other
        history writes, failing to create it stops the run from starting."""
        if self._history is not None:
            await self._history.create_run(run_id, goal)

    async def owns(self, run_id: str) -> bool:
        """Does the current user own this run? Without a database there is only one user."""
        return await self._history.is_mine(run_id) if self._history is not None else True

    async def history(self, run_id: str):
        """Full run history from the database (steps + every tool call), or None."""
        return await self._history.history(run_id) if self._history is not None else None

    async def approve(self, run_id: str, decision: ApprovalDecision) -> None:
        """Resume a run that is waiting for approval."""
        await self.graph.ainvoke(Command(resume=decision.model_dump()), self._config(run_id))

    async def continue_run(self, run_id: str) -> None:
        """Continue an interrupted run (e.g. the server stopped mid-run) from its last checkpoint."""
        await self.graph.ainvoke(None, self._config(run_id))

    async def start_in_background(self, goal: str) -> str:
        """Create the run's row FIRST, then start working. The caller gets the run id
        only once the run exists, so an immediate GET /agent/runs/{id} never 404s."""
        run_id = uuid4().hex
        await self._create_row(run_id, goal)
        self._starting[run_id] = goal
        self._spawn(run_id, self.start(goal, run_id, row_created=True))
        return run_id

    def approve_in_background(self, run_id: str, decision: ApprovalDecision) -> None:
        self._crashes.pop(run_id, None)
        self._spawn(run_id, self.approve(run_id, decision))

    def continue_in_background(self, run_id: str) -> None:
        self._crashes.pop(run_id, None)
        self._spawn(run_id, self.continue_run(run_id))

    def is_running(self, run_id: str) -> bool:
        task = self._background.get(run_id)
        return task is not None and not task.done()

    def _spawn(self, run_id: str, work) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception as exc:
                # The checkpoint is left untouched on purpose: it still points at the node
                # that was running, so the run stays RESUMABLE with continue_run().
                logger.exception("Run %s crashed", run_id[:8])
                self._crashes[run_id] = f"{type(exc).__name__}: {exc}"
            finally:
                self._background.pop(run_id, None)
                self._starting.pop(run_id, None)

        # Keep a reference: asyncio only keeps WEAK references to tasks, so an
        # unreferenced background task can be garbage-collected mid-run.
        self._background[run_id] = asyncio.create_task(guarded())

    async def shutdown(self) -> None:
        """Cancel running workers. Their last checkpoint stays: resume later with continue_run."""
        for task in list(self._background.values()):
            task.cancel()
        await asyncio.gather(*self._background.values(), return_exceptions=True)

    async def get(self, run_id: str) -> RunView | None:
        snapshot = await self.graph.aget_state(self._config(run_id))
        values = snapshot.values
        if not values:
            if run_id in self._starting and self.is_running(run_id):
                # Accepted, but the worker hasn't saved its first checkpoint yet. Without
                # this, a client polling right after the 202 would get "Run not found".
                return RunView(run_id=run_id, goal=self._starting[run_id], status=RunStatus.PLANNING.value,
                               running=True, next_nodes=[])
            return None
        pending = [
            task
            for item in snapshot.interrupts
            if isinstance(item.value, dict) and item.value.get("type") == "approval"
            for task in item.value.get("tasks", [])
        ]
        running = self.is_running(run_id)
        return RunView(
            run_id=run_id,
            goal=values.get("goal", ""),
            status=values.get("status", ""),
            created_at=values.get("created_at", ""),
            running=running,
            # Unfinished, not running, not waiting for a human = it was interrupted
            # (server stopped, worker crashed). continue_run() picks it up again.
            resumable=bool(snapshot.next) and not running and not pending,
            next_nodes=list(snapshot.next),
            plan=values.get("plan"),
            planning=values.get("planning"),
            records=values.get("records", []),
            steps_used=values.get("steps_used", 0),
            pending_approvals=pending,
            evaluation=values.get("evaluation"),
            evaluation_history=values.get("evaluation_history", []),
            replans=values.get("replans", 0),
            final_output=values.get("final_output"),
            stop_reason=values.get("stop_reason"),
            error=values.get("error") or self._crashes.get(run_id),
        )

    async def list_runs(self, limit: int = 20) -> list[RunView]:
        """Most recent runs first.

        With a database: the `tasks` table is the runs INDEX (one indexed, ordered query,
        LIMIT N, only the current user's runs), then only those runs are loaded from
        their checkpoints. If that query fails, the error propagates: scanning the
        checkpoints instead would list EVERY user's runs.
        Without a database (single user): scan the checkpoints (slow with many runs)."""
        if self._history is not None:
            rows = await self._history.list_runs(limit)
            return [v for v in [await self.get(r.run_id) for r in rows] if v is not None]
        thread_ids: list[str] = []
        async for checkpoint in self.checkpointer.alist(None, limit=2_000):
            thread_id = checkpoint.config["configurable"]["thread_id"]
            if thread_id not in thread_ids:
                thread_ids.append(thread_id)
        views = [v for v in [await self.get(t) for t in thread_ids] if v is not None]
        views.sort(key=lambda v: v.created_at, reverse=True)
        return views[:limit]
