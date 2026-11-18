"""The catalog of tools the agent is ALLOWED to use. This is an allowlist.

The planner shows this list to the LLM and rejects any plan that uses a tool not
listed here. Phase 4 attaches a real implementation to each name.

`requires_approval` is decided HERE, in code, by us. We never let the LLM decide
whether an action is sensitive: a manipulated model could simply say "no approval needed".
"""

from pydantic import BaseModel, ConfigDict


class ToolSpec(BaseModel):
    """Description of one tool, as the planner (and the LLM) sees it."""

    model_config = ConfigDict(frozen=True)  # immutable: nobody can change it at runtime

    name: str
    description: str
    requires_approval: bool = False


TOOL_CATALOG: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="web_search",
        description="Search the web for current information. Input: one search query. "
        "Returns titles, URLs and snippets of the top results.",
    ),
    ToolSpec(
        name="read_file",
        description="Read an uploaded PDF, TXT or DOCX file from the allowed documents folder.",
    ),
    ToolSpec(
        name="search_knowledge_base",
        description="Semantic search over documents previously stored in the knowledge base (RAG).",
    ),
    ToolSpec(
        name="calculator",
        description="Evaluate a math expression exactly, e.g. averages, percentages, totals.",
    ),
    ToolSpec(
        name="llm_analysis",
        description="Reason over the results of earlier tasks: extract, compare, rank, "
        "summarize. No external access.",
    ),
    ToolSpec(
        name="generate_report",
        description="Write a structured Markdown report from the results of earlier tasks.",
    ),
    ToolSpec(
        name="database_query",
        description="Read saved data (past reports, task history, memories) from the database.",
    ),
    ToolSpec(
        name="save_to_database",
        description="Save a result, report, or application record to the agent's database.",
    ),
    ToolSpec(
        name="python_exec",
        description="Run a short Python snippet in a restricted sandbox for data processing.",
        requires_approval=True,  # running generated code is risky: a human must confirm
    ),
    ToolSpec(
        name="send_email",
        description="Send an email on the user's behalf.",
        requires_approval=True,  # affects the outside world: always ask the human
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {tool.name: tool for tool in TOOL_CATALOG}


def render_tool_catalog(tools: tuple[ToolSpec, ...] | list[ToolSpec] = TOOL_CATALOG) -> str:
    """Format the tools as a bullet list for the planner prompt."""
    lines = []
    for tool in tools:
        note = " [needs human approval]" if tool.requires_approval else ""
        lines.append(f"- {tool.name}: {tool.description}{note}")
    return "\n".join(lines)
