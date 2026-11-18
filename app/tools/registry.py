"""ToolRegistry: the single gate every tool call passes through.

    execute(name, args)
      1. allowlist   - is the tool registered (and in the catalog)?
      2. approval    - does it need human approval, and do we have it?
      3. validation  - do the arguments match the tool's Pydantic schema?
      4. policy      - permission policy on the REAL arguments: disabled tools, email
                       allowlist, no secrets leaving the machine, budgets, rate limits
      5. timeout     - stop tools that hang
      6. errors      - turn every failure into a ToolResult (never crash the agent)
      7. injection   - flag outside content that looks like instructions to the AI
      8. limits      - cut oversized output
      9. audit log   - record what ran, how long it took, and how it ended

Because both the API and the LLM (via as_langchain_tools) go through execute(),
the same safety rules apply no matter who calls the tool.
"""

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.safety.injection import scan_for_injection, warning_for
from app.safety.permissions import PermissionPolicy
from app.tools.base import AgentTool, ToolError, ToolResult, ToolStatus
from app.tools.catalog import TOOLS_BY_NAME, ToolSpec

logger = logging.getLogger(__name__)

# Tools whose output is text written by someone else (web pages, files, stored data).
EXTERNAL_CONTENT_TOOLS = frozenset({"web_search", "read_file", "search_knowledge_base", "database_query"})


class ToolRegistry:
    def __init__(
        self,
        *,
        catalog: Mapping[str, ToolSpec] = TOOLS_BY_NAME,
        timeout_seconds: float = 30.0,
        max_output_chars: int = 8_000,
        policy: PermissionPolicy | None = None,
        scan_for_injection: bool = False,
    ) -> None:
        self._catalog = dict(catalog)
        self._tools: dict[str, AgentTool] = {}
        self._timeout = timeout_seconds
        self._timeouts: dict[str, float] = {}  # per-tool overrides
        self._max_output_chars = max_output_chars
        self._policy = policy
        self._scan = scan_for_injection

    # ------------------------------------------------------------ registration
    def register(self, tool: AgentTool, *, timeout_seconds: float | None = None) -> None:
        """Add a tool. Only names from the catalog (the allowlist) are accepted.

        timeout_seconds overrides the default timeout for this one tool.
        """
        if tool.name not in self._catalog:
            raise ValueError(f"Tool '{tool.name}' is not in the tool catalog (allowlist).")
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        if timeout_seconds is not None:
            self._timeouts[tool.name] = timeout_seconds

    def input_model(self, name: str):
        """The Pydantic input model of a registered tool (the executor builds arguments for it)."""
        return self._tools[name].input_model

    def available_specs(self) -> list[ToolSpec]:
        """Catalog entries of the tools that are actually registered right now.
        The planner plans ONLY with these, so it never picks a tool that can't run."""
        return [spec for name, spec in self._catalog.items() if name in self._tools]

    def is_available(self, name: str) -> bool:
        return name in self._tools

    def spec(self, name: str) -> ToolSpec:
        return self._catalog[name]

    def describe(self) -> list[dict[str, Any]]:
        """Every catalog tool, whether it is implemented yet, and its input schema."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "requires_approval": spec.requires_approval,
                "available": spec.name in self._tools,
                "input_schema": (
                    self._tools[spec.name].input_model.model_json_schema()
                    if spec.name in self._tools
                    else None
                ),
            }
            for spec in self._catalog.values()
        ]

    # --------------------------------------------------------------- execution
    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
        run_id: str | None = None,
    ) -> ToolResult:
        """Run a tool safely. Always returns a ToolResult; never raises.

        run_id identifies the agent run, for per-run budgets (None = no run budget).
        """
        started = time.perf_counter()
        arguments = dict(arguments or {})

        def finish(
            status: ToolStatus, output: str = "", error: str | None = None, flags: list[str] | None = None
        ) -> ToolResult:
            truncated = len(output) > self._max_output_chars
            if truncated:
                output = output[: self._max_output_chars] + "\n...[output truncated]"
            result = ToolResult(
                tool_name=name,
                status=status,
                output=output,
                error=error,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                truncated=truncated,
                security_flags=flags or [],
            )
            # Audit log: arguments are shortened so big inputs and file text stay out of logs.
            logger.info(
                "TOOL %s status=%s %.0fms args=%s",
                name,
                status.value,
                result.duration_ms,
                str(arguments)[:200],
            )
            return result

        # 1. Allowlist
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "none"
            return finish(ToolStatus.ERROR, error=f"Unknown tool '{name}'. Available: {available}.")

        # 2. Permission: blocked BEFORE validation or execution, so nothing runs.
        if self._catalog[name].requires_approval and not approved:
            return finish(ToolStatus.NEEDS_APPROVAL, error="Human approval required.")

        # 3. Validation
        try:
            args = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
            )
            return finish(ToolStatus.ERROR, error=f"Invalid arguments: {problems}")

        # 4. Permission policy, checked on the validated REAL arguments.
        if self._policy is not None:
            permission = self._policy.authorize(name, args, run_id=run_id)
            if not permission.allowed:
                logger.warning("DENIED %s: %s", name, permission.reason)
                return finish(ToolStatus.DENIED, error=permission.reason)

        # 5 + 6. Run with a timeout, and convert every failure into a result.
        timeout = self._timeouts.get(name, self._timeout)
        try:
            async with asyncio.timeout(timeout):
                output = await tool.run(args)
        except TimeoutError:
            return finish(ToolStatus.TIMEOUT, error=f"Timed out after {timeout:g} seconds.")
        except ToolError as exc:  # expected problem: show its message
            return finish(ToolStatus.ERROR, error=str(exc))
        except Exception as exc:  # bug or library failure: log details, show a short message
            logger.exception("Tool %s crashed", name)
            return finish(ToolStatus.ERROR, error=f"Unexpected {type(exc).__name__} in tool.")

        # 7. Injection scan on content that came from outside.
        output = str(output)
        flags: list[str] = []
        if self._scan and name in EXTERNAL_CONTENT_TOOLS:
            flags = scan_for_injection(output)
            if flags:
                logger.warning("Possible prompt injection in %s output: %s", name, ", ".join(flags))
                output = warning_for(flags) + output  # the LLM sees the label before the content
        return finish(ToolStatus.SUCCESS, output=output, flags=flags)

    # ----------------------------------------------------- LLM function calling
    def as_langchain_tools(self, *, include_approval_required: bool = False) -> list[StructuredTool]:
        """Expose registered tools to an LLM (Phase 2's bind_tools / run_with_tools).

        Every call the LLM makes is routed through execute(), so validation, timeouts
        and approval checks still apply. Approval-required tools are hidden by default.
        """
        tools = []
        for name, tool in self._tools.items():
            spec = self._catalog[name]
            if spec.requires_approval and not include_approval_required:
                continue
            tools.append(
                StructuredTool.from_function(
                    coroutine=self._make_caller(name),
                    name=name,
                    description=spec.description,
                    args_schema=tool.input_model,
                )
            )
        return tools

    def _make_caller(self, name: str):
        # A separate function creates a new `name` for each tool. Defining the
        # closure directly inside the loop would make every tool call the LAST name.
        async def call(**kwargs: Any) -> str:
            return (await self.execute(name, kwargs)).to_llm_text()

        return call


def build_default_registry(
    settings: Settings | None = None, database=None, knowledge_base=None, llm_factory=None
) -> ToolRegistry:
    """Create a registry with every implemented tool, configured from settings.

    `database` is an app.database.connection.Database; `knowledge_base` is an
    app.rag.retrieval.KnowledgeBase; `llm_factory` is a zero-argument function returning
    an LLMService (for llm_analysis / generate_report). Tools whose dependency is None
    are left out (the planner will see them as unavailable).
    """
    # Imported here to avoid circular imports and to keep startup light.
    from app.tools.calculator import CalculatorTool
    from app.tools.database_tool import DatabaseQueryTool, SaveToDatabaseTool
    from app.tools.email_tool import SendEmailTool
    from app.tools.file_reader import FileReaderTool
    from app.tools.knowledge_base_tool import SearchKnowledgeBaseTool
    from app.tools.llm_tools import GenerateReportTool, LLMAnalysisTool
    from app.tools.python_tool import PythonExecTool
    from app.tools.web_search import WebSearchTool, make_search_provider

    settings = settings or get_settings()
    registry = ToolRegistry(
        timeout_seconds=settings.tool_timeout_seconds,
        max_output_chars=settings.tool_max_output_chars,
        policy=PermissionPolicy.from_settings(settings),
        scan_for_injection=settings.injection_scan_enabled,
    )

    def add(tool: AgentTool, **options: Any) -> None:
        # Disabled tools are not even registered, so the planner never sees them.
        # (The policy also denies them: defense in depth.)
        if tool.name not in settings.disabled_tools:
            registry.register(tool, **options)

    add(CalculatorTool())
    add(WebSearchTool(make_search_provider(settings), settings.search_max_results))
    add(FileReaderTool(settings.documents_dir, max_file_size_mb=settings.max_file_size_mb))
    add(PythonExecTool(timeout_seconds=settings.python_exec_timeout_seconds))
    add(SendEmailTool(settings.email_outbox_dir, database=database))
    if database is not None:
        add(SaveToDatabaseTool(database))
        add(DatabaseQueryTool(database))
    if knowledge_base is not None:
        add(SearchKnowledgeBaseTool(knowledge_base))
    if llm_factory is not None:
        # LLM calls can legitimately take longer than ordinary tools.
        llm_timeout = max(settings.tool_timeout_seconds, settings.llm_timeout_seconds)
        add(LLMAnalysisTool(llm_factory), timeout_seconds=llm_timeout)
        add(GenerateReportTool(llm_factory), timeout_seconds=llm_timeout)
    return registry
