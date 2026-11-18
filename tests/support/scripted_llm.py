"""A deterministic stand-in for the LLM, for integration and end-to-end tests.

Built with create_autospec(LLMService): it has exactly the real class's methods and
signatures, but answers from a script instead of calling Gemini. No quota, no network,
same answer every time, so a failing test always points at OUR code.

The script:
  goal mentions "email" -> plan: t1 calculator -> t2 send_email (needs approval)
  any other goal        -> plan: t1 calculator -> t2 generate_report
  "remember that X"     -> the chat stores X as a memory
"""

import re
from unittest.mock import create_autospec

from langchain_core.messages import BaseMessage

from app.agent.schemas import PlanDraft, PlannedTask
from app.llm.schemas import GoalAnalysis
from app.llm.service import LLMService
from app.memory.schemas import MemoryExtraction, MemoryOperation

EMAIL_TO = "mentor@example.com"
REPORT = "# Average salary report\n\nThe average of the three salaries is **52,666.67**.\n"

# Tool arguments by field name (the executor may ask for a SUBSET model of a tool's input).
TOOL_ARGS = {
    "expression": "(45000 + 52000 + 61000) / 3",
    "to": [EMAIL_TO],
    "subject": "Average salary",
    "body": "The average salary is 52666.67.",
    "instructions": "Write a short report about the average salary.",
    "query": "average salary",
    "kind": "note",
    "title": "Average salary",
    "content": "52666.67",
}


def _text(messages) -> str:
    if isinstance(messages, str):
        return messages
    return "\n".join(str(m.content) for m in messages if isinstance(m, BaseMessage))


def _task(task_id: str, tool: str, title: str, deps: list[str]) -> PlannedTask:
    return PlannedTask(id=task_id, title=title, description=title, tool=tool, depends_on=deps,
                       priority="high", expected_output="a result")


def plan_for(text: str) -> PlanDraft:
    # Look ONLY inside <goal>...</goal>: the rest of the planner prompt lists every tool,
    # including send_email, so searching the whole prompt would always find "email".
    goal = re.search(r"<goal>(.*?)</goal>", text, flags=re.DOTALL)
    if "email" in (goal.group(1) if goal else text).lower():
        second = _task("t2", "send_email", "Email the result to my mentor", ["t1"])
    else:
        second = _task("t2", "generate_report", "Write the report", ["t1"])
    return PlanDraft(strategy="Calculate the average, then deliver it.",
                     tasks=[_task("t1", "calculator", "Calculate the average salary", []), second])


def scripted_llm() -> LLMService:
    llm = create_autospec(LLMService, instance=True)

    async def analyze_goal(goal: str) -> GoalAnalysis:
        return GoalAnalysis(summary=goal[:200], category="analysis", deliverables=["report"],
                            required_capabilities=["calculation"], is_clear=True, clarifying_questions=[])

    async def structured(messages, schema):
        text = _text(messages)
        if schema is PlanDraft:
            return plan_for(text)
        if schema is MemoryExtraction:
            # The last line holding "remember that ..." is the user's newest message.
            found = re.findall(r"remember that (.+)", text, flags=re.IGNORECASE)
            if not found:
                return MemoryExtraction(operations=[])
            fact = found[-1].strip().rstrip(".")[:200]
            return MemoryExtraction(operations=[MemoryOperation(action="add", content=f"User said: {fact}.",
                                                                category="preference", importance=4)])
        fields = {name: TOOL_ARGS[name] for name in schema.model_fields if name in TOOL_ARGS}
        return schema(**fields)  # unscripted required fields fail loudly (ValidationError)

    async def generate(messages, *, label: str = "chat") -> str:
        return REPORT if label in {"report", "analysis"} else "Hello from the scripted model."

    async def chat(user_message: str, **_kwargs) -> str:
        return "Hello from the scripted model."

    llm.analyze_goal.side_effect = analyze_goal
    llm.structured.side_effect = structured
    llm.generate.side_effect = generate
    llm.chat.side_effect = chat
    return llm
