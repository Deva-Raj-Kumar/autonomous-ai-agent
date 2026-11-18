"""Pydantic schemas for STRUCTURED OUTPUTS.

Instead of asking the LLM for free text and parsing it with string tricks, we give
it a schema. The provider forces the reply into valid JSON matching the schema, and
Pydantic turns that JSON into a typed Python object (or raises if it doesn't fit).

The `description` on each Field is sent to the model: it is part of the prompt.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Literal types become JSON-schema "enum"s: the model can only pick from these values.
GoalCategory = Literal["research", "analysis", "writing", "data_processing", "calculation", "other"]

Capability = Literal[
    "web_search",
    "file_reading",
    "knowledge_base",
    "calculation",
    "database",
    "report_generation",
]


class GoalAnalysis(BaseModel):
    """The agent's understanding of a user goal. Phase 3's planner builds on this."""

    summary: str = Field(description="One sentence restating what the user wants.")
    category: GoalCategory = Field(description="The main type of work the goal requires.")
    deliverables: list[str] = Field(
        description="Concrete outputs the user expects, e.g. 'comparison table', 'saved report'."
    )
    required_capabilities: list[Capability] = Field(
        description="Which agent capabilities are needed to achieve the goal."
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Limits stated or implied by the user: locations, counts, dates, formats.",
    )
    sensitive_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Actions that must need human approval: sending emails, submitting applications, "
            "deleting data, payments. Empty if none."
        ),
    )
    is_clear: bool = Field(description="True if the goal is specific enough to start working.")
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Questions to ask the user if the goal is unclear. Empty if is_clear is true.",
    )


class ToolCallRecord(BaseModel):
    """One tool call the model requested, and what happened when we ran it."""

    tool_name: str
    arguments: dict
    output: str
    success: bool


class ToolRunResult(BaseModel):
    """Final result of a function-calling conversation."""

    answer: str
    tool_calls: list[ToolCallRecord]
    rounds: int = Field(description="How many model calls were needed.")
