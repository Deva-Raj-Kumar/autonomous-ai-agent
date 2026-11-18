"""Building blocks shared by every tool.

- AgentTool:  the base class each tool extends (a name, an input schema, an async run()).
- ToolResult: the ONE return type of every tool execution, success or failure.
- ToolError:  raise it inside a tool for an expected problem ("file not found").
              Its message is shown to the LLM, so keep it clear and free of secrets.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field


class ToolError(Exception):
    """An expected tool failure with a safe, human-readable message."""


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"  # bad input, tool failure, unknown tool...
    TIMEOUT = "timeout"
    NEEDS_APPROVAL = "needs_approval"  # blocked until a human approves
    DENIED = "denied"  # blocked by the permission policy (Phase 10)


class ToolResult(BaseModel):
    """Outcome of one tool execution. Tools never raise to the agent; they return this."""

    tool_name: str
    status: ToolStatus
    output: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    truncated: bool = False
    # Possible prompt-injection patterns found in outside content (Phase 10).
    security_flags: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    def to_llm_text(self) -> str:
        """The text the LLM sees as the tool's answer."""
        if self.ok:
            return self.output
        if self.status == ToolStatus.NEEDS_APPROVAL:
            return f"'{self.tool_name}' requires human approval and was not run."
        if self.status == ToolStatus.DENIED:
            return f"'{self.tool_name}' was blocked by the permission policy: {self.error}"
        return f"Error from {self.tool_name}: {self.error}"


class AgentTool(ABC):
    """Base class for all tools.

    Subclasses set two class attributes and implement run():
        name        - must match an entry in app/tools/catalog.py (the allowlist)
        input_model - Pydantic model describing and validating the arguments
    The description and approval rule come from the catalog, so they live in one place.
    """

    name: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, args: BaseModel) -> str:
        """Do the work and return text for the LLM. `args` is already validated."""
