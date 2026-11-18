"""The AI Planner: turns a natural-language goal into a validated, ordered Plan.

Pipeline:
    goal
     -> 1. understand   (LLMService.analyze_goal, from Phase 2)
     -> 2. clarify?     unclear goal -> return questions instead of guessing
     -> 3. draft        LLM proposes a PlanDraft (structured output)
     -> 4. validate     OUR code checks tools, dependencies, cycles, size
     -> 5. repair       invalid? send the exact errors back to the LLM and retry (limited)
     -> 6. build        Plan with approval flags from the tool catalog + execution order

The key idea: the LLM proposes, deterministic code verifies.
"""

import logging
from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage

from app.agent.plan_graph import find_graph_errors
from app.agent.schemas import Plan, PlanDraft, PlanningResult, Task
from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.llm.prompts import PLAN_REPAIR_MESSAGE, PLANNER_PROMPT, REPLAN_FEEDBACK_TEMPLATE
from app.llm.schemas import GoalAnalysis
from app.llm.service import LLMService
from app.tools.catalog import TOOL_CATALOG, ToolSpec, render_tool_catalog

logger = logging.getLogger(__name__)


class PlanningError(LLMError):
    """Raised when no valid plan could be produced within the attempt limit."""


class Planner:
    """Creates execution plans for user goals."""

    def __init__(
        self,
        llm: LLMService,
        *,
        tools: Sequence[ToolSpec] = TOOL_CATALOG,
        max_tasks: int = 12,
        max_attempts: int = 3,
    ) -> None:
        self._llm = llm
        self._tools = {tool.name: tool for tool in tools}
        self._tool_catalog_text = render_tool_catalog(list(tools))
        self._max_tasks = max_tasks
        self._max_attempts = max_attempts

    @classmethod
    def from_settings(
        cls, llm: LLMService, settings: Settings | None = None, tools: Sequence[ToolSpec] | None = None
    ) -> "Planner":
        """`tools`: the tools available right now (registry.available_specs()). Defaults
        to the whole catalog, which is fine for planning-only use."""
        settings = settings or get_settings()
        return cls(
            llm,
            tools=tools if tools is not None else TOOL_CATALOG,
            max_tasks=settings.max_plan_tasks,
            max_attempts=settings.planner_max_attempts,
        )

    async def create_plan(self, goal: str, *, feedback: str | None = None) -> PlanningResult:
        """Run the full planning pipeline for one goal.

        feedback: when RE-planning, the evaluator's report on why the last plan failed,
        so the new plan is different instead of repeating the same mistakes.
        """
        # 1. Understand the goal.
        analysis = await self._llm.analyze_goal(goal)
        logger.info("Goal analysis: category=%s clear=%s", analysis.category, analysis.is_clear)

        # 2. Unclear goal: ask, don't guess. Guessing wastes tool calls and money.
        if not analysis.is_clear:
            return PlanningResult(
                status="needs_clarification",
                analysis=analysis,
                clarifying_questions=analysis.clarifying_questions,
                attempts=0,
            )

        # 3-5. Draft, validate and repair.
        messages: list[BaseMessage] = PLANNER_PROMPT.invoke(
            {
                "tool_catalog": self._tool_catalog_text,
                "max_tasks": self._max_tasks,
                "goal": goal,
                "analysis": analysis.model_dump_json(indent=2),
                "feedback": REPLAN_FEEDBACK_TEMPLATE.format(feedback=feedback) if feedback else "",
            }
        ).to_messages()

        errors: list[str] = []
        for attempt in range(1, self._max_attempts + 1):
            draft = await self._llm.structured(messages, PlanDraft)
            errors = self.validate_draft(draft)
            if not errors:
                plan = self._build_plan(goal, analysis, draft)  # 6. build
                logger.info(
                    "Plan %s created: %d tasks, %d waves, attempt %d",
                    plan.id[:8],
                    len(plan.tasks),
                    len(plan.parallel_groups),
                    attempt,
                )
                return PlanningResult(
                    status="planned", analysis=analysis, plan=plan, attempts=attempt
                )

            logger.warning("Plan attempt %d rejected: %s", attempt, errors)
            # Keep the conversation and add precise feedback, so the model can fix it.
            messages = [
                *messages,
                HumanMessage(
                    PLAN_REPAIR_MESSAGE.format(
                        errors="\n".join(f"- {e}" for e in errors),
                        previous_plan=draft.model_dump_json(indent=2),
                    )
                ),
            ]

        raise PlanningError(
            f"Could not create a valid plan in {self._max_attempts} attempts. "
            f"Last problems: {'; '.join(errors)}"
        )

    def validate_draft(self, draft: PlanDraft) -> list[str]:
        """Check an LLM draft. Returns problems in plain English (empty = valid).

        The messages are written for the LLM to read in the repair step, so they
        say exactly what is wrong and what is allowed.
        """
        errors = find_graph_errors(draft.tasks)  # ids, dependencies, cycles

        if len(draft.tasks) > self._max_tasks:
            errors.append(
                f"The plan has {len(draft.tasks)} tasks; the maximum is {self._max_tasks}. "
                "Merge or remove tasks."
            )

        valid_names = ", ".join(self._tools)
        for task in draft.tasks:
            if task.tool not in self._tools:
                errors.append(
                    f"Task {task.id} uses unknown tool '{task.tool}'. Valid tools: {valid_names}."
                )
            if not task.description.strip() or not task.title.strip():
                errors.append(f"Task {task.id} needs a non-empty title and description.")
        return errors

    def _build_plan(self, goal: str, analysis: GoalAnalysis, draft: PlanDraft) -> Plan:
        """Turn a valid draft into a Plan. Approval flags come from OUR tool catalog."""
        tasks = [
            Task(
                **planned.model_dump(),
                requires_approval=self._tools[planned.tool].requires_approval,
            )
            for planned in draft.tasks
        ]
        return Plan(goal=goal, analysis=analysis, strategy=draft.strategy, tasks=tasks)
