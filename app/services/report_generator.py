"""Report generator: turns the results of earlier tasks into a Markdown report.

Used by the `generate_report` tool. Kept as a separate service so other parts of the
app (the API's report download in Phase 12, the dashboard in Phase 13) can reuse it.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.prompts import REPORT_SYSTEM_PROMPT, wrap_untrusted
from app.llm.service import LLMService

MAX_CONTEXT_CHARS = 30_000  # keep the prompt (and its cost) bounded


class ReportGenerator:
    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def generate(self, instructions: str, context: str) -> str:
        """Write the report. `context` is the collected output of earlier tasks."""
        context = context[:MAX_CONTEXT_CHARS]
        messages = [
            SystemMessage(REPORT_SYSTEM_PROMPT),
            HumanMessage(
                f"Report instructions:\n{instructions}\n\n"
                f"Context from earlier steps:\n{wrap_untrusted(context, source='task_results')}"
            ),
        ]
        return (await self._llm.generate(messages, label="report")).strip()
