"""Evaluator: checks the agent's work and decides what happens next.

Three layers, cheapest first:
  1. Task completion checks (rules):  FAILED tasks; can a retry fix the error?
  2. Evidence validation (code):      are the URLs/numbers in analyses and reports backed
                                      by primary sources? (app/agent/evidence.py)
  3. LLM judge (1 structured call):   does each result match its expected_output?
                                      Is the goal achieved? Is the plan itself viable?

THE LLM JUDGES, CODE DECIDES. The judge only returns scores and issues; this module turns
them into exactly one bounded decision:
    REPLAN       goal not achieved AND the judge says retries can't fix the plan
    RETRY_TASKS  send specific tasks back, each with the reviewer's feedback
    ACCEPT       done; unresolved problems are reported as "open issues"
Retry rounds and replans have hard limits, so evaluation can never loop forever.
"""

import logging
from enum import StrEnum

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.evidence import check_plan_evidence
from app.agent.schemas import Plan, Task, TaskStatus
from app.config import Settings
from app.llm.client import LLMError
from app.llm.prompts import JUDGE_SYSTEM_PROMPT, wrap_untrusted
from app.llm.service import LLMService
from app.safety.injection import scan_for_injection
from app.tools.registry import EXTERNAL_CONTENT_TOOLS

logger = logging.getLogger(__name__)

# Errors that another attempt cannot fix: retrying would just waste steps.
NON_RETRYABLE_MARKERS = (
    "is not available", "Access denied", "File type not allowed", "Rejected by the user",
    "Permission denied",  # policy denials: retrying can't change the policy
)
JUDGE_RESULT_CHARS = 1_500  # per task, in the judge prompt
MAX_FACTS_IN_FEEDBACK = 10


class Verdict(StrEnum):
    ACCEPT = "accept"
    RETRY_TASKS = "retry_tasks"
    REPLAN = "replan"


class TaskJudgement(BaseModel):
    task_id: str
    passed: bool
    score: int = Field(ge=0, le=10)
    issues: list[str] = Field(default_factory=list)
    fix_hint: str = ""


class EvidenceSummary(BaseModel):
    task_id: str
    checked: int
    unsupported: list[str]


class Evaluation(BaseModel):
    verdict: Verdict
    reason: str
    mode: str = "rules"
    retry_task_ids: list[str] = Field(default_factory=list)
    feedback: dict[str, str] = Field(default_factory=dict, description="task_id -> what to fix")
    open_issues: list[str] = Field(default_factory=list, description="Problems left unresolved.")
    task_judgements: list[TaskJudgement] = Field(default_factory=list)
    evidence: list[EvidenceSummary] = Field(default_factory=list)
    goal_achieved: bool | None = None
    quality_score: float | None = Field(default=None, description="0-10, average judge score.")
    replan_feedback: str | None = None
    judge_error: str | None = None


# ------------------------------------------------------------ LLM-facing
class _JudgeTask(BaseModel):
    task_id: str = Field(description="The task id exactly as shown, e.g. 't2'.")
    passed: bool = Field(description="True only if the result delivers the expected output.")
    score: int = Field(description="0 (useless/wrong) to 10 (complete and correct).")
    issues: list[str] = Field(default_factory=list, description="Concrete problems, if any.")
    fix_hint: str = Field(default="", description="How a retry could do better, in one sentence.")


class _JudgeOutput(BaseModel):
    tasks: list[_JudgeTask]
    goal_achieved: bool = Field(description="Does the work as a whole answer the user's goal?")
    plan_is_viable: bool = Field(description="Can retrying tasks fix the problems? False = a new plan is needed.")
    summary: str = Field(description="2-3 sentences: overall quality and the main problems.")


# ------------------------------------------------------------ rules only
def is_retryable(error: str | None) -> bool:
    return not any(marker in (error or "") for marker in NON_RETRYABLE_MARKERS)


def evaluate_execution(plan: Plan, *, rounds_used: int, max_rounds: int) -> Evaluation:
    """Rule-based evaluation (no LLM): retry retryable failures while rounds remain."""
    failed = [t for t in plan.tasks if t.status == TaskStatus.FAILED]
    if not failed:
        return Evaluation(verdict=Verdict.ACCEPT, reason="No failed tasks.")
    feedback = {t.id: f"Previous attempt failed: {t.error}" for t in failed if is_retryable(t.error)}
    unfixable = [f"{t.id} failed: {t.error}" for t in failed if not is_retryable(t.error)]
    if not feedback:
        return Evaluation(verdict=Verdict.ACCEPT, reason="Failures can't be fixed by retrying.", open_issues=unfixable)
    if rounds_used >= max_rounds:
        return Evaluation(
            verdict=Verdict.ACCEPT,
            reason=f"Retry rounds used up ({rounds_used}/{max_rounds}); accepting a partial result.",
            open_issues=unfixable + [f"{tid}: {text}" for tid, text in feedback.items()],
        )
    return Evaluation(
        verdict=Verdict.RETRY_TASKS,
        reason=f"Retrying {len(feedback)} failed task(s), round {rounds_used + 1}/{max_rounds}.",
        retry_task_ids=list(feedback),
        feedback=feedback,
        open_issues=unfixable,
    )


# ---------------------------------------------------------- full evaluator
class Evaluator:
    def __init__(
        self,
        llm: LLMService | None,
        *,
        mode: str = "llm",
        pass_score: int = 5,
        max_rounds: int = 1,
        max_replans: int = 1,
    ) -> None:
        self._llm = llm
        self._mode = mode if llm is not None else "rules"
        self._pass_score = pass_score
        self._max_rounds = max_rounds
        self._max_replans = max_replans

    @classmethod
    def from_settings(cls, llm: LLMService | None, settings: Settings) -> "Evaluator":
        return cls(
            llm,
            mode=settings.evaluation_mode,
            pass_score=settings.judge_pass_score,
            max_rounds=settings.max_evaluation_rounds,
            max_replans=settings.max_replans,
        )

    async def evaluate(self, plan: Plan, *, rounds_used: int = 0, replans_used: int = 0) -> Evaluation:
        feedback: dict[str, list[str]] = {}
        open_issues: list[str] = []

        # 1. Task completion checks.
        for task in plan.tasks:
            if task.status != TaskStatus.FAILED:
                continue
            if is_retryable(task.error):
                feedback.setdefault(task.id, []).append(f"Previous attempt failed: {task.error}")
            else:
                open_issues.append(f"{task.id} failed: {task.error}")

        # 2. Evidence validation.
        evidence = check_plan_evidence(plan)
        for task_id, result in evidence.items():
            if result.unsupported:
                facts = ", ".join(result.unsupported[:MAX_FACTS_IN_FEEDBACK])
                feedback.setdefault(task_id, []).append(
                    f"These facts were not found in any source; remove them or correct them from the sources: {facts}"
                )
        summaries = [
            EvidenceSummary(task_id=tid, checked=r.checked_numbers + r.checked_urls, unsupported=r.unsupported)
            for tid, r in evidence.items()
        ]

        # Security: tell the user when outside content tried to instruct the AI (Phase 10).
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED and task.tool in EXTERNAL_CONTENT_TOOLS:
                labels = scan_for_injection(task.result or "")
                if labels:
                    open_issues.append(
                        f"{task.id}: possible prompt injection in outside content ({', '.join(labels)}); "
                        "it was treated as data, not as instructions."
                    )

        # 3. LLM judge.
        judge: _JudgeOutput | None = None
        judge_error: str | None = None
        judged = [t for t in plan.tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
        if self._mode == "llm" and any(t.status == TaskStatus.COMPLETED for t in judged):
            try:
                judge = await self._judge(plan, judged, summaries)
            except LLMError as exc:  # the judge is a bonus: fall back to rules + evidence
                judge_error = f"LLM judge unavailable: {exc}"
                logger.warning(judge_error)

        judgements = self._apply_judge(plan, judge, feedback) if judge else []
        quality = round(sum(j.score for j in judgements) / len(judgements), 1) if judgements else None
        flat_feedback = {tid: " ".join(items) for tid, items in feedback.items()}
        common = {
            "mode": "llm" if judge else "rules",
            "task_judgements": judgements,
            "evidence": summaries,
            "goal_achieved": judge.goal_achieved if judge else None,
            "quality_score": quality,
            "judge_error": judge_error,
        }

        # ---- decide (code, not the LLM) ----
        if judge and not judge.goal_achieved and not judge.plan_is_viable and replans_used < self._max_replans:
            issues = [f"{j.task_id}: {'; '.join(j.issues)}" for j in judgements if j.issues]
            return Evaluation(
                verdict=Verdict.REPLAN,
                reason=f"The plan can't reach the goal; re-planning ({replans_used + 1}/{self._max_replans}).",
                replan_feedback="\n".join([judge.summary, *issues, *open_issues]),
                open_issues=open_issues,
                **common,
            )
        if flat_feedback and rounds_used < self._max_rounds:
            return Evaluation(
                verdict=Verdict.RETRY_TASKS,
                reason=f"Sending {len(flat_feedback)} task(s) back with feedback, round {rounds_used + 1}/{self._max_rounds}.",
                retry_task_ids=list(flat_feedback),
                feedback=flat_feedback,
                open_issues=open_issues,
                **common,
            )
        open_issues += [f"{tid}: {text}" for tid, text in flat_feedback.items()]
        if judge and not judge.goal_achieved:
            open_issues.append(f"The reviewer judged the goal NOT fully achieved: {judge.summary}")
        if not open_issues:
            reason = "All checks passed."
        elif flat_feedback:  # we wanted to retry, but the budget is spent: say so
            reason = (
                f"Retry rounds used up ({rounds_used}/{self._max_rounds}); "
                f"accepted with {len(open_issues)} open issue(s)."
            )
        else:
            reason = f"Accepted with {len(open_issues)} open issue(s)."
        return Evaluation(verdict=Verdict.ACCEPT, reason=reason, open_issues=open_issues, **common)

    async def _judge(self, plan: Plan, tasks: list[Task], evidence: list[EvidenceSummary]) -> _JudgeOutput:
        blocks = []
        for t in tasks:
            body = (
                f"Result:\n{wrap_untrusted((t.result or '')[:JUDGE_RESULT_CHARS], source=f'task_{t.id}')}"
                if t.status == TaskStatus.COMPLETED
                else f"FAILED with error: {t.error}"
            )
            blocks.append(
                f"[{t.id}] tool={t.tool} status={t.status.value}\n"
                f"What to do: {t.description}\nExpected output: {t.expected_output}\n{body}"
            )
        evidence_lines = [
            f"- {e.task_id}: {len(e.unsupported)} of {e.checked} facts NOT found in sources: {', '.join(e.unsupported[:10])}"
            if e.unsupported
            else f"- {e.task_id}: all {e.checked} checked facts found in sources"
            for e in evidence
        ] or ["- not applicable (no analysis/report with primary sources)"]
        human = (
            f"User goal: {plan.goal}\n\nTasks:\n\n" + "\n\n".join(blocks)
            + "\n\nAutomatic evidence check:\n" + "\n".join(evidence_lines)
        )
        return await self._llm.structured([SystemMessage(JUDGE_SYSTEM_PROMPT), HumanMessage(human)], _JudgeOutput)

    def _apply_judge(self, plan: Plan, judge: _JudgeOutput, feedback: dict[str, list[str]]) -> list[TaskJudgement]:
        """Validate the judge's output in code: ignore unknown task ids, clamp scores,
        and turn low-scoring results into retry feedback."""
        known = {t.id: t for t in plan.tasks}
        judgements = []
        for item in judge.tasks:
            task = known.get(item.task_id)
            if task is None or task.status != TaskStatus.COMPLETED:
                continue  # the LLM proposes, code verifies: no made-up task ids
            judgement = TaskJudgement(
                task_id=item.task_id, passed=item.passed, score=max(0, min(10, item.score)),
                issues=item.issues, fix_hint=item.fix_hint,
            )
            judgements.append(judgement)
            if not judgement.passed and judgement.score < self._pass_score:
                note = "Reviewer: " + ("; ".join(judgement.issues) or "result rejected")
                if judgement.fix_hint:
                    note += f" Hint: {judgement.fix_hint}"
                feedback.setdefault(item.task_id, []).append(note)
        return judgements


# ------------------------------------------------------------------ retries
def descendants(plan: Plan, task_ids: set[str]) -> set[str]:
    """Every task that depends (directly or indirectly) on any of `task_ids`."""
    found: set[str] = set()
    frontier = set(task_ids)
    while frontier:
        children = {t.id for t in plan.tasks if set(t.depends_on) & frontier} - found
        found |= children
        frontier = children
    return found


def reset_for_retry(plan: Plan, task_ids: list[str], feedback: dict[str, str] | None = None) -> None:
    """Send tasks back for another round.

    - The retried tasks become PENDING with the reviewer's feedback attached.
    - Their DESCENDANTS are reset too: their inputs are about to change, so their old
      results (or dependency-skips) are no longer valid.
    - Tasks the user rejected stay rejected.
    """
    feedback = feedback or {}
    retry = set(task_ids)
    for task in plan.tasks:
        if task.id in retry:
            task.status, task.result, task.error = TaskStatus.PENDING, None, None
            task.feedback = feedback.get(task.id)
            # Approved arguments are for ONE specific action. A retry generates new ones,
            # which need a NEW approval (the workflow also drops the old approval).
            task.proposed_arguments = None
    for task_id in descendants(plan, retry):
        task = plan.get_task(task_id)
        skipped_for_dependency = task.status == TaskStatus.SKIPPED and (task.error or "").startswith(
            "Skipped: dependency"
        )
        if task.status == TaskStatus.COMPLETED or skipped_for_dependency:
            task.status, task.result, task.error = TaskStatus.PENDING, None, None
            task.proposed_arguments = None
