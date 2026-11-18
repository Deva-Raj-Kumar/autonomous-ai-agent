"""Task Executor: runs a validated Plan, task by task, until the goal is done.

    loop:
      1. skip tasks whose dependency FAILED or was SKIPPED (they can never run)
      2. take the READY tasks (all dependencies completed)
      3. tasks needing approval -> WAITING_APPROVAL (not run; Phase 10 adds the approve step)
      4. run the rest of the wave IN PARALLEL (at most N at once):
           a. build the tool arguments   (ArgumentBuilder below)
           b. execute via ToolRegistry   (allowlist, validation, timeout, audit: Phase 4)
           c. failed? retry with the error fed back, with exponential backoff
           d. success: store the result in WorkingMemory for dependent tasks
      5. repeat until nothing is ready, or a safety limit (steps / run time) is hit
    finally: final status + final output (the report, or an LLM summary of the results)

Safety limits, so an autonomous loop can never run away:
  - max_steps: every tool attempt (retries included) costs one step
  - max_retries per task, with backoff (1s, 2s, 4s...) so failing APIs aren't hammered
  - run timeout for the whole run
  - a semaphore caps parallel tasks (protects rate limits)
"""

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError, create_model

from app.agent.schemas import (
    ExecutionEvent,
    ExecutionResult,
    ExecutionStatus,
    Plan,
    Task,
    TaskRunRecord,
    TaskStatus,
)
from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.llm.prompts import FINAL_ANSWER_SYSTEM_PROMPT, TOOL_ARGUMENTS_PROMPT, wrap_untrusted
from app.llm.service import LLMService
from app.memory.short_term import WorkingMemory
from app.tools.base import ToolResult, ToolStatus
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

EventCallback = Callable[[ExecutionEvent], Awaitable[None] | None]

# Fields the EXECUTOR fills from data it already has, instead of asking the LLM to copy
# them. "task" = the task's own instructions; "dependencies" = results of earlier tasks.
# Passing large data by code is cheaper, can't be mistyped, and gives a prompt
# injection inside a web page no chance to rewrite the data on the way.
AUTO_FILLED_FIELDS: dict[str, dict[str, str]] = {
    "llm_analysis": {"instructions": "task", "context": "dependencies"},
    "generate_report": {"instructions": "task", "context": "dependencies"},
    "save_to_database": {"content": "dependencies"},
}
# Reasoning tools see the results of ALL earlier tasks they depend on (directly or
# indirectly), not just direct dependencies: a report written only from the analysis
# loses the evidence (search results, URLs) the analysis was based on.
CONTEXT_FROM_ALL_ANCESTORS = {"llm_analysis", "generate_report"}
ARGUMENT_PROMPT_CONTEXT_CHARS = 12_000  # dependency results shown to the argument builder
AUTO_FILL_CONTEXT_CHARS = 30_000  # dependency results passed straight into a tool
RECORD_VALUE_CHARS = 300  # long argument values are shortened in the audit records
FINAL_SUMMARY_CONTEXT_CHARS = 20_000


def ancestors(plan: Plan, task: Task) -> set[str]:
    """Ids of every task `task` depends on, directly or through other tasks."""
    found: set[str] = set()
    stack = list(task.depends_on)
    while stack:
        task_id = stack.pop()
        if task_id not in found:
            found.add(task_id)
            stack.extend(plan.get_task(task_id).depends_on)
    return found


# --------------------------------------------------------------- arguments
class ArgumentBuilder:
    """Turns a task ("search AI jobs in Hyderabad") into concrete tool arguments
    ({"query": "AI engineer fresher jobs Hyderabad", "max_results": 5})."""

    def __init__(self, llm: LLMService, registry: ToolRegistry) -> None:
        self._llm = llm
        self._registry = registry
        self._models: dict[tuple[str, frozenset[str]], type[BaseModel] | None] = {}

    async def build(
        self, task: Task, *, goal: str, dependency_results: str, previous_error: str | None = None
    ) -> dict[str, Any]:
        auto = self.auto_fields(task, dependency_results)
        model = self.llm_model(task.tool, frozenset(auto))
        if model is None:  # code already filled every field: no LLM call needed
            return auto

        spec = self._registry.spec(task.tool)
        if previous_error:  # this run's last attempt failed
            retry_note = f"\nThe previous attempt FAILED with this error:\n{previous_error}\nFix the input."
        elif task.feedback:  # the evaluator rejected an earlier result (Phase 9)
            retry_note = (
                f"\nA reviewer checked this task's previous result and found problems:\n"
                f"{task.feedback}\nChange the input so the new result fixes them."
            )
        else:
            retry_note = ""
        context = (
            wrap_untrusted(dependency_results[:ARGUMENT_PROMPT_CONTEXT_CHARS], source="earlier_tasks")
            if dependency_results
            else "(none)"
        )
        messages = TOOL_ARGUMENTS_PROMPT.invoke(
            {
                "goal": goal,
                "task_id": task.id,
                "title": task.title,
                "description": task.description,
                "expected_output": task.expected_output,
                "tool_name": spec.name,
                "tool_description": spec.description,
                "context": context,
                "retry_note": retry_note,
            }
        ).to_messages()
        generated = await self._llm.structured(messages, model)
        return {**generated.model_dump(), **auto}  # auto-filled values always win

    @staticmethod
    def auto_fields(task: Task, dependency_results: str) -> dict[str, str]:
        instructions = f"{task.description}\nExpected output: {task.expected_output}"
        if task.feedback:  # reasoning tools get the reviewer's notes inside their instructions
            instructions += f"\n\nA reviewer rejected the previous version. Fix these problems:\n{task.feedback}"
        sources = {
            "task": instructions,
            "dependencies": dependency_results[:AUTO_FILL_CONTEXT_CHARS],
        }
        filled = {field: sources[src] for field, src in AUTO_FILLED_FIELDS.get(task.tool, {}).items()}
        # Leave a field to the LLM if there is no data for it (e.g. no dependencies).
        return {field: value for field, value in filled.items() if value.strip()}

    def llm_model(self, tool: str, exclude: frozenset[str]) -> type[BaseModel] | None:
        """The tool's input model MINUS the auto-filled fields (None if nothing is left).

        create_model builds a new Pydantic class at runtime, reusing each field's
        type, default, limits and description, so the LLM sees the same schema.
        """
        key = (tool, exclude)
        if key not in self._models:
            source = self._registry.input_model(tool)
            fields = {n: (f.annotation, f) for n, f in source.model_fields.items() if n not in exclude}
            self._models[key] = create_model(f"{source.__name__}Args", **fields) if fields else None
        return self._models[key]


# ---------------------------------------------------------------- executor
class _RunState:
    def __init__(self, plan: Plan, memory: WorkingMemory) -> None:
        self.plan = plan
        self.memory = memory
        self.steps = 0
        self.records: list[TaskRunRecord] = []
        self.step_limit_hit = False


class TaskExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        llm: LLMService,
        *,
        max_steps: int = 15,
        max_retries: int = 2,
        run_timeout_seconds: float = 300.0,
        retry_delay_seconds: float = 1.0,
        max_parallel: int = 4,
        max_result_chars: int = 8_000,
        approved_task_ids: frozenset[str] = frozenset(),
        on_event: EventCallback | None = None,
        run_id: str | None = None,
    ) -> None:
        self._registry = registry
        self._llm = llm
        self._run_id = run_id  # for per-run tool budgets in the permission policy
        self._arguments = ArgumentBuilder(llm, registry)
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._run_timeout = run_timeout_seconds
        self._retry_delay = retry_delay_seconds
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._max_result_chars = max_result_chars
        self._approved = approved_task_ids
        self._on_event = on_event

    @classmethod
    def from_settings(
        cls, registry: ToolRegistry, llm: LLMService, settings: Settings | None = None, **overrides: Any
    ) -> "TaskExecutor":
        settings = settings or get_settings()
        options: dict[str, Any] = {
            "max_steps": settings.max_agent_steps,
            "max_retries": settings.max_task_retries,
            "run_timeout_seconds": settings.agent_run_timeout_seconds,
            "retry_delay_seconds": settings.agent_retry_delay_seconds,
            "max_parallel": settings.agent_max_parallel_tasks,
            "max_result_chars": settings.tool_max_output_chars,
        }
        return cls(registry, llm, **{**options, **overrides})

    # -------------------------------------------------------------- the run
    async def execute(
        self,
        plan: Plan,
        *,
        steps_used: int = 0,
        max_waves: int | None = None,
        produce_final_output: bool = True,
    ) -> ExecutionResult:
        """Run the plan.

        steps_used:  steps already spent earlier in this run (the budget is per RUN).
        max_waves:   stop after this many waves (the LangGraph workflow runs ONE wave per
                     node, so a checkpoint is saved after every wave).
        produce_final_output: False when the caller builds the final output later.
        """
        started = time.perf_counter()
        state = _RunState(plan, WorkingMemory(plan.goal, max_entries=200, max_entry_chars=self._max_result_chars))
        state.steps = steps_used
        # A resumed run starts with an empty WorkingMemory: refill it from the results
        # already stored in the plan, so dependent tasks still get their inputs.
        for task_id in plan.execution_order:
            done = plan.get_task(task_id)
            if done.status == TaskStatus.COMPLETED and done.result is not None:
                state.memory.add("task_result", done.result, done.id)
        await self._emit("run_started", message=plan.goal)

        stop_reason: str | None = None
        try:
            async with asyncio.timeout(self._run_timeout):
                await self._run_loop(state, max_waves)
        except TimeoutError:
            stop_reason = f"Run time limit of {self._run_timeout:g} seconds reached."
            for task in plan.tasks:  # tasks cut off mid-flight
                if task.status == TaskStatus.RUNNING:
                    task.status, task.error = TaskStatus.FAILED, "Stopped by the run time limit."
        if state.step_limit_hit and stop_reason is None:
            stop_reason = f"Step limit of {self._max_steps} reached."
        await self._skip_blocked(plan)

        status = self.final_status(plan, stop_reason)
        final_output = await self.compose_final_output(plan) if produce_final_output else None
        result = ExecutionResult(
            goal=plan.goal,
            status=status,
            plan=plan,
            final_output=final_output,
            records=state.records,
            steps_used=state.steps,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            pending_approvals=[t.id for t in plan.tasks if t.status == TaskStatus.WAITING_APPROVAL],
            stop_reason=stop_reason,
        )
        logger.info(
            "RUN %s status=%s steps=%d/%d %.1fs", result.run_id[:8], status.value,
            state.steps, self._max_steps, result.duration_ms / 1000,
        )
        await self._emit("run_finished", message=f"{status.value}" + (f": {stop_reason}" if stop_reason else ""))
        return result

    async def _run_loop(self, state: _RunState, max_waves: int | None = None) -> None:
        plan = state.plan
        waves = 0
        while max_waves is None or waves < max_waves:
            waves += 1
            await self._skip_blocked(plan)
            runnable: list[Task] = []
            for task in plan.ready_tasks():
                if task.requires_approval and task.id not in self._approved:
                    await self._propose(task, state)  # build the exact arguments, THEN pause
                else:
                    runnable.append(task)
            if not runnable:
                return  # done, or everything left is waiting/blocked
            if state.steps >= self._max_steps:
                state.step_limit_hit = True
                return
            # asyncio.gather runs the whole wave concurrently and waits for all of it.
            await asyncio.gather(*(self._run_task(task, state) for task in runnable))
            if state.step_limit_hit:
                return

    def _dependency_results(self, task: Task, state: _RunState) -> str:
        source_ids = (
            ancestors(state.plan, task) if task.tool in CONTEXT_FROM_ALL_ANCESTORS else set(task.depends_on)
        )
        # render() drops the OLDEST entries first when over budget, so the direct
        # dependencies (finished most recently) survive and raw early results go first.
        return state.memory.render(task_ids=source_ids, max_chars=AUTO_FILL_CONTEXT_CHARS) if source_ids else ""

    async def _propose(self, task: Task, state: _RunState) -> None:
        """APPROVE WHAT YOU SEE: generate the exact arguments (the code, the email recipient
        and body...) BEFORE pausing, so the human approves the real action, not a vague
        description. After approval, precisely these arguments run."""
        if not self._registry.is_available(task.tool):
            await self._fail(task, state, f"Tool '{task.tool}' is not available.")
            return
        try:
            arguments = await self._arguments.build(
                task, goal=state.plan.goal, dependency_results=self._dependency_results(task, state)
            )
            # Validate now: the human must never approve arguments the tool would reject.
            validated = self._registry.input_model(task.tool).model_validate(arguments)
        except (LLMError, ValidationError) as exc:
            await self._fail(task, state, f"Could not prepare the arguments for approval: {exc}")
            return
        task.proposed_arguments = validated.model_dump(mode="json")
        task.status = TaskStatus.WAITING_APPROVAL
        await self._emit("task_skipped", task.id, "waiting for human approval")

    async def _run_task(self, task: Task, state: _RunState) -> None:
        async with self._semaphore:  # at most max_parallel tasks run at the same time
            task.status = TaskStatus.RUNNING
            await self._emit("task_started", task.id, f"{task.title} ({task.tool})")

            if not self._registry.is_available(task.tool):  # retrying can't fix this
                await self._fail(task, state, f"Tool '{task.tool}' is not available.")
                return

            # Approved with shown arguments -> run EXACTLY those, on every attempt.
            # Regenerating them would run something the human never saw.
            locked = task.id in self._approved and task.proposed_arguments is not None
            dependency_results = "" if locked else self._dependency_results(task, state)
            error: str | None = None
            for attempt in range(1, self._max_retries + 2):
                if state.steps >= self._max_steps:
                    state.step_limit_hit = True
                    error = f"Step limit reached before attempt {attempt}. Last error: {error}"
                    break
                state.steps += 1  # check + increment have no await between them: race-free
                task.attempts = attempt
                started = time.perf_counter()

                try:
                    arguments = (
                        dict(task.proposed_arguments)
                        if locked
                        else await self._arguments.build(
                            task, goal=state.plan.goal, dependency_results=dependency_results, previous_error=error
                        )
                    )
                except (LLMError, ValidationError) as exc:
                    error = f"Could not prepare the tool input: {exc}"
                    state.records.append(self._record(task, attempt, {}, "error", error=error, started=started))
                else:
                    result = await self._registry.execute(
                        task.tool, arguments, approved=task.id in self._approved, run_id=self._run_id
                    )
                    state.records.append(self._record_result(task, attempt, arguments, result, started))
                    if result.ok:
                        task.status, task.result, task.error = TaskStatus.COMPLETED, result.output, None
                        task.feedback = None  # addressed: don't carry stale feedback forward
                        state.memory.add("task_result", result.output, task.id)
                        logger.info("TASK %s completed (%s, attempt %d)", task.id, task.tool, attempt)
                        await self._emit("task_finished", task.id, f"completed (attempt {attempt})")
                        return
                    if result.status == ToolStatus.NEEDS_APPROVAL:
                        # Defense in depth: the registry refused even though the plan said
                        # no approval was needed. Trust the registry, and show the human the
                        # arguments that were about to run.
                        task.requires_approval, task.proposed_arguments = True, arguments
                        task.status, task.error = TaskStatus.WAITING_APPROVAL, result.error
                        await self._emit("task_skipped", task.id, "waiting for human approval")
                        return
                    error = result.error
                    if result.status == ToolStatus.DENIED and not (error or "").startswith("Rate limit"):
                        break  # a policy denial won't change on retry: stop now, save the steps

                if attempt <= self._max_retries:
                    logger.warning("TASK %s attempt %d failed: %s", task.id, attempt, error)
                    await asyncio.sleep(self._retry_delay * 2 ** (attempt - 1))  # 1s, 2s, 4s...

            await self._fail(task, state, error or "Unknown error.")

    async def _fail(self, task: Task, state: _RunState, error: str) -> None:
        task.status, task.error = TaskStatus.FAILED, error
        state.memory.add("observation", f"Task failed: {error}", task.id)
        logger.warning("TASK %s failed: %s", task.id, error)
        await self._emit("task_finished", task.id, f"failed: {error}")

    async def _skip_blocked(self, plan: Plan) -> None:
        """A pending task whose dependency failed or was skipped can never run: skip it.
        Repeats until stable, because skipping one task can block the next."""
        dead = {TaskStatus.FAILED, TaskStatus.SKIPPED}
        changed = True
        while changed:
            changed = False
            for task in plan.tasks:
                if task.status != TaskStatus.PENDING:
                    continue
                blocker = next((d for d in task.depends_on if plan.get_task(d).status in dead), None)
                if blocker:
                    task.status = TaskStatus.SKIPPED
                    task.error = f"Skipped: dependency {blocker} {plan.get_task(blocker).status.value}."
                    await self._emit("task_skipped", task.id, task.error)
                    changed = True

    @staticmethod
    def final_status(plan: Plan, stop_reason: str | None) -> ExecutionStatus:
        statuses = [t.status for t in plan.tasks]
        if TaskStatus.WAITING_APPROVAL in statuses:
            return ExecutionStatus.WAITING_APPROVAL
        if stop_reason:
            return ExecutionStatus.STOPPED
        if all(s == TaskStatus.COMPLETED for s in statuses):
            return ExecutionStatus.COMPLETED
        if TaskStatus.COMPLETED in statuses:
            return ExecutionStatus.PARTIAL
        return ExecutionStatus.FAILED

    async def compose_final_output(self, plan: Plan) -> str | None:
        """The report if one was generated; otherwise an LLM summary of the results."""
        completed = [plan.get_task(i) for i in plan.execution_order if plan.get_task(i).status == TaskStatus.COMPLETED]
        if not completed:
            return None
        reports = [t for t in completed if t.tool == "generate_report"]
        if reports:
            return reports[-1].result

        lines = [f"[{t.id}] {t.title} -> {t.status.value}: {(t.result or t.error or '')}" for t in plan.tasks]
        try:
            return await self._llm.generate(
                [
                    SystemMessage(FINAL_ANSWER_SYSTEM_PROMPT),
                    HumanMessage(
                        f"Goal: {plan.goal}\n\nTask results:\n"
                        + wrap_untrusted("\n".join(lines)[:FINAL_SUMMARY_CONTEXT_CHARS], source="task_results")
                    ),
                ],
                label="final_answer",
            )
        except LLMError as exc:  # never lose the run's results because the summary failed
            logger.warning("Final summary failed, returning the last result: %s", exc)
            return completed[-1].result

    # -------------------------------------------------------------- helpers
    def _record(
        self, task: Task, attempt: int, arguments: dict, status: str, *,
        output: str = "", error: str | None = None, started: float, security_flags: list[str] | None = None,
    ) -> TaskRunRecord:
        shortened = {
            k: (v[:RECORD_VALUE_CHARS] + "...") if isinstance(v, str) and len(v) > RECORD_VALUE_CHARS else v
            for k, v in arguments.items()
        }
        return TaskRunRecord(
            task_id=task.id, attempt=attempt, tool=task.tool, arguments=shortened, status=status,
            output_preview=output[:RECORD_VALUE_CHARS], error=error,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            security_flags=security_flags or [],
        )

    def _record_result(
        self, task: Task, attempt: int, arguments: dict, result: ToolResult, started: float
    ) -> TaskRunRecord:
        return self._record(
            task, attempt, arguments, result.status.value, output=result.output,
            error=result.error, started=started, security_flags=result.security_flags,
        )

    async def _emit(self, kind: str, task_id: str | None = None, message: str = "") -> None:
        if self._on_event is None:
            return
        try:
            outcome = self._on_event(ExecutionEvent(kind=kind, task_id=task_id, message=message))
            if inspect.isawaitable(outcome):  # the callback may be sync or async
                await outcome
        except Exception:  # a broken progress display must never break the run
            logger.exception("Execution event callback failed")
