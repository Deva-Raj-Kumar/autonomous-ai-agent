"""Tests for the restricted Python tool: static checks, real execution, limits."""

import pytest

from app.tools.base import ToolError
from app.tools.python_tool import PythonExecInput, PythonExecTool, check_code_safety, minimal_environment


@pytest.mark.parametrize(
    "code",
    [
        "x = [n * n for n in range(5)]\nprint(x)",
        "import math\nprint(math.sqrt(2))",
        "from statistics import mean\nprint(mean([1, 2, 3]))",
        "import collections.abc",
    ],
)
def test_safe_code_passes_check(code: str) -> None:
    assert check_code_safety(code) == []


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("import os", "Import of 'os'"),
        ("import subprocess", "Import of 'subprocess'"),
        ("from os import path", "Import from 'os'"),
        ("from . import secrets", "Import from"),
        ("open('x.txt')", "'open'"),
        ("eval('1+1')", "'eval'"),
        ("__import__('os')", "'__import__'"),
        ("print(__builtins__)", "'__builtins__'"),
        ("().__class__.__bases__[0].__subclasses__()", "private attribute"),
        ("getattr(1, 'real')", "'getattr'"),
        ("def f(:\n  pass", "Syntax error"),
    ],
)
def test_dangerous_code_is_rejected(code: str, reason: str) -> None:
    problems = check_code_safety(code)

    assert problems, f"should be rejected: {code!r}"
    assert any(reason in p for p in problems)


def test_child_environment_contains_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "should-not-leak")

    env = minimal_environment()

    assert "GOOGLE_API_KEY" not in env
    assert set(env) <= {"SYSTEMROOT"}


@pytest.mark.anyio
async def test_runs_code_in_subprocess() -> None:
    output = await PythonExecTool().run(
        PythonExecInput(code="import statistics\nprint(statistics.mean([6, 7.5, 9]))")
    )

    assert output.strip() == "7.5"


@pytest.mark.anyio
async def test_runtime_error_is_reported() -> None:
    with pytest.raises(ToolError, match="ZeroDivisionError"):
        await PythonExecTool().run(PythonExecInput(code="print(1 / 0)"))


@pytest.mark.anyio
async def test_infinite_loop_is_killed() -> None:
    with pytest.raises(ToolError, match="did not finish within 1 seconds"):
        await PythonExecTool(timeout_seconds=1).run(PythonExecInput(code="while True:\n    pass"))


@pytest.mark.anyio
async def test_unsafe_code_never_runs() -> None:
    with pytest.raises(ToolError, match="rejected by safety check"):
        await PythonExecTool().run(PythonExecInput(code="import os\nos.remove('x')"))


@pytest.mark.anyio
async def test_timed_out_process_is_killed_mocked() -> None:
    """Mocked version of the timeout test: no real process, runs instantly, and proves
    that kill() and wait() are called, which the real test can't easily observe."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    async def never_finishes():
        await asyncio.sleep(10)

    fake_process = MagicMock()
    fake_process.returncode = None  # "still running"
    fake_process.communicate = AsyncMock(side_effect=never_finishes)
    fake_process.wait = AsyncMock(return_value=-9)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_process)) as spawn:
        with pytest.raises(ToolError, match="did not finish within 0.05 seconds"):
            await PythonExecTool(timeout_seconds=0.05).run(PythonExecInput(code="print(1)"))

    fake_process.kill.assert_called_once()
    fake_process.wait.assert_awaited_once()
    args = spawn.await_args.args
    assert args[1:4] == ("-I", "-X", "utf8")  # isolated mode flags were used
    assert spawn.await_args.kwargs["env"] == minimal_environment()  # no secrets passed
