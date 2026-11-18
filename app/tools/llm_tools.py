"""Reasoning tools: `llm_analysis` and `generate_report`.

These tools have no outside effects: they let the LLM think over the results of
earlier tasks. They are still registered in the ToolRegistry, so they get the same
validation, timeout, audit logging and ToolResult handling as every other tool.

The LLM is created lazily through a factory: the registry is built at startup, and
the app must still start even if no API key is configured yet.
"""

from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm.prompts import ANALYSIS_SYSTEM_PROMPT, wrap_untrusted
from app.llm.service import LLMService
from app.services.report_generator import ReportGenerator
from app.tools.base import AgentTool

MAX_CONTEXT_CHARS = 30_000


class ReasoningInput(BaseModel):
    instructions: str = Field(min_length=1, max_length=4_000, description="What to analyze or write.")
    context: str = Field(
        default="",
        max_length=60_000,
        description="Results of earlier tasks. Filled in automatically by the executor.",
    )


class _LLMBackedTool(AgentTool):
    input_model = ReasoningInput

    def __init__(self, llm_factory: Callable[[], LLMService]) -> None:
        self._llm_factory = llm_factory
        self._llm: LLMService | None = None

    @property
    def llm(self) -> LLMService:
        if self._llm is None:
            self._llm = self._llm_factory()
        return self._llm


class LLMAnalysisTool(_LLMBackedTool):
    name = "llm_analysis"

    async def run(self, args: ReasoningInput) -> str:  # type: ignore[override]
        messages = [
            SystemMessage(ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(
                f"Instructions:\n{args.instructions}\n\n"
                f"Context:\n{wrap_untrusted(args.context[:MAX_CONTEXT_CHARS] or '(none)', source='task_results')}"
            ),
        ]
        return (await self.llm.generate(messages, label="analysis")).strip()


class GenerateReportTool(_LLMBackedTool):
    name = "generate_report"

    async def run(self, args: ReasoningInput) -> str:  # type: ignore[override]
        return await ReportGenerator(self.llm).generate(args.instructions, args.context)
