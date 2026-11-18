"""Tests for ToolRegistry: allowlist, approval, validation, timeout, errors, limits.

Each fake tool is a MagicMock(spec=AgentTool) whose async run() is an AsyncMock,
so tests can assert exactly whether, and with what, the tool was run.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.tools.base import AgentTool, ToolError, ToolStatus
from app.tools.calculator import CalculatorTool
from app.tools.catalog import ToolSpec
from app.tools.registry import ToolRegistry

pytestmark = pytest.mark.anyio

# A small test catalog, so these tests don't depend on the real one.
CATALOG = {
    "calculator": ToolSpec(name="calculator", description="math"),
    "echo": ToolSpec(name="echo", description="repeat text"),
    "danger": ToolSpec(name="danger", description="risky", requires_approval=True),
}


class EchoInput(BaseModel):
    text: str


def mock_tool(name: str, output: str = "ok") -> MagicMock:
    """A mock tool. spec=AgentTool keeps it honest (only real AgentTool attributes)."""
    tool = MagicMock(spec=AgentTool)
    tool.name = name
    tool.input_model = EchoInput
    tool.run = AsyncMock(return_value=output)
    return tool


@pytest.fixture
def echo() -> MagicMock:
    return mock_tool("echo", output="hi")


@pytest.fixture
def danger() -> MagicMock:
    return mock_tool("danger", output="did something risky")


def make_registry(echo: MagicMock, danger: MagicMock, **kwargs) -> ToolRegistry:
    registry = ToolRegistry(catalog=CATALOG, **kwargs)
    registry.register(echo)
    registry.register(danger)
    registry.register(CalculatorTool())  # one real tool, for the LangChain bridge test
    return registry


def test_only_catalog_tools_can_be_registered() -> None:
    with pytest.raises(ValueError, match="not in the tool catalog"):
        ToolRegistry(catalog=CATALOG).register(mock_tool("delete_everything"))


def test_duplicate_registration_rejected(echo, danger) -> None:
    registry = make_registry(echo, danger)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(mock_tool("echo"))


async def test_success_passes_validated_arguments(echo, danger) -> None:
    result = await make_registry(echo, danger).execute("echo", {"text": "hi"})

    assert result.status == ToolStatus.SUCCESS and result.output == "hi"
    echo.run.assert_awaited_once_with(EchoInput(text="hi"))  # a validated model, not a dict


async def test_unknown_tool(echo, danger) -> None:
    result = await make_registry(echo, danger).execute("rm_rf", {})

    assert result.status == ToolStatus.ERROR
    assert "Unknown tool 'rm_rf'" in result.error


async def test_invalid_arguments_are_explained(echo, danger) -> None:
    result = await make_registry(echo, danger).execute("echo", {"txt": "typo in name"})

    assert result.status == ToolStatus.ERROR
    assert "text: Field required" in result.error
    echo.run.assert_not_awaited()  # never ran


async def test_approval_required_blocks_before_running(echo, danger) -> None:
    result = await make_registry(echo, danger).execute("danger", {"text": "x"})

    assert result.status == ToolStatus.NEEDS_APPROVAL
    assert "requires human approval" in result.to_llm_text()
    danger.run.assert_not_awaited()


async def test_approved_tool_runs(echo, danger) -> None:
    result = await make_registry(echo, danger).execute("danger", {"text": "ok"}, approved=True)

    assert result.ok
    danger.run.assert_awaited_once()


async def test_timeout(echo, danger) -> None:
    async def slow(args):
        await asyncio.sleep(1)

    echo.run.side_effect = slow  # side_effect=function: the mock runs it when awaited

    result = await make_registry(echo, danger, timeout_seconds=0.05).execute("echo", {"text": "x"})

    assert result.status == ToolStatus.TIMEOUT


async def test_tool_error_message_is_shown(echo, danger) -> None:
    echo.run.side_effect = ToolError("expected problem")

    result = await make_registry(echo, danger).execute("echo", {"text": "x"})

    assert result.status == ToolStatus.ERROR and result.error == "expected problem"


async def test_unexpected_crash_hides_internal_details(echo, danger) -> None:
    echo.run.side_effect = RuntimeError("secret internal detail")

    result = await make_registry(echo, danger).execute("echo", {"text": "x"})

    assert result.status == ToolStatus.ERROR
    assert "RuntimeError" in result.error
    assert "secret internal detail" not in result.error


async def test_long_output_is_truncated(echo, danger) -> None:
    echo.run.return_value = "a" * 2_000

    result = await make_registry(echo, danger, max_output_chars=500).execute("echo", {"text": "x"})

    assert result.truncated is True
    assert result.output.endswith("[output truncated]") and len(result.output) < 600


def test_describe_marks_unavailable_tools() -> None:
    registry = ToolRegistry(catalog=CATALOG)
    registry.register(CalculatorTool())

    info = {t["name"]: t for t in registry.describe()}

    assert info["calculator"]["available"] is True
    assert info["calculator"]["input_schema"]["properties"]["expression"]
    assert info["echo"]["available"] is False


async def test_langchain_tools_hide_approval_tools_and_use_registry(echo, danger) -> None:
    tools = {t.name: t for t in make_registry(echo, danger).as_langchain_tools()}

    assert set(tools) == {"echo", "calculator"}  # "danger" is hidden
    assert await tools["calculator"].ainvoke({"expression": "6 * 7"}) == "6 * 7 = 42"
    assert await tools["echo"].ainvoke({"text": "via langchain"}) == "hi"
    echo.run.assert_awaited_once_with(EchoInput(text="via langchain"))  # went through execute()
