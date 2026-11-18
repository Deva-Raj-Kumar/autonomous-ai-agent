"""Restricted Python execution for small data-processing snippets.

HONEST WARNING: truly sandboxing Python inside Python is not possible. This tool uses
DEFENSE IN DEPTH, several independent layers, so that one mistake isn't fatal:

  1. Human approval  - the catalog marks python_exec requires_approval=True, so the
                       registry refuses to run it until a person says yes.
  2. Static check    - parse the code (AST) and reject imports outside a small allowlist,
                       dangerous built-ins (open, eval, exec, __import__...) and any
                       _private/__dunder__ attribute (the usual way to escape restrictions).
  3. Separate process - code runs in a NEW Python process: a crash or infinite loop
                       can't take down the server, and it's killed after a timeout.
  4. Clean environment - the child process gets NO environment variables except the bare
                       minimum, so API keys in your environment are not visible to it.
                       It runs in an empty temporary folder, in isolated mode (-I).

In production you would add an OS-level sandbox: a Docker container with no network,
a read-only filesystem and CPU/memory limits, or a service like gVisor or Firecracker.
"""

import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

from pydantic import BaseModel, Field

from app.config import DATA_DIR
from app.tools.base import AgentTool, ToolError

ALLOWED_MODULES = frozenset(
    {"math", "statistics", "json", "re", "datetime", "collections", "itertools",
     "functools", "random", "decimal", "fractions", "string", "textwrap", "csv", "io",
     "pandas", "openpyxl"}
)
BLOCKED_NAMES = frozenset(
    {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
     "getattr", "setattr", "delattr", "breakpoint", "help", "exit", "quit", "memoryview"}
)
MAX_OUTPUT_CHARS = 10_000


def check_code_safety(code: str) -> list[str]:
    """Return a list of reasons the code is rejected (empty list = allowed)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntax error on line {exc.lineno}: {exc.msg}"]

    problems: list[str] = []
    for node in ast.walk(tree):  # visits every node in the syntax tree
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    problems.append(f"Import of '{alias.name}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                problems.append(f"Import from '{node.module}' is not allowed.")
        elif isinstance(node, ast.Name) and (node.id in BLOCKED_NAMES or node.id.startswith("__")):
            if node.id == "open":
                problems.append(
                    "Use of 'open' is not allowed: file disk access is blocked in this sandbox. "
                    "Format your CSV/data in memory (e.g. using io.StringIO and csv.writer) and output it using print()."
                )
            else:
                problems.append(f"Use of '{node.id}' is not allowed.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            problems.append(f"Access to private attribute '.{node.attr}' is not allowed.")

    allowed = ", ".join(sorted(ALLOWED_MODULES))
    if any("Import" in p for p in problems):
        problems.append(f"Allowed modules: {allowed}.")
    return problems


def minimal_environment() -> dict[str, str]:
    """Only what Windows needs to start Python. Nothing else, so no secrets."""
    env = {}
    if sys.platform == "win32":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


async def run_python(code: str, timeout_seconds: float) -> str:
    """Run code in a separate, isolated Python process and return its printed output."""
    generated_files: list[tuple[str, int]] = []
    cmd = [
        sys.executable,
        "-I",  # isolated mode: ignore PYTHON* env vars, user site-packages, script dir
        "-X", "utf8",  # UTF-8 output on every platform
        "-c", code,
    ]
    env = minimal_environment()

    with tempfile.TemporaryDirectory(prefix="agent_py_") as workdir:
        stdout_text = ""
        stderr_text = ""
        returncode = 0

        try:
            # Try async subprocess (works on ProactorEventLoop and POSIX loops)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workdir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout_seconds)
                stdout_text = stdout_b.decode("utf-8", errors="replace")
                stderr_text = stderr_b.decode("utf-8", errors="replace")
                returncode = process.returncode or 0
            except TimeoutError:
                raise ToolError(f"Code did not finish within {timeout_seconds:g} seconds.") from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        except NotImplementedError:
            # Windows SelectorEventLoop does not implement async subprocess transport.
            # Gracefully fall back to thread-pool subprocess execution:
            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    cwd=workdir,
                    env=env,
                    capture_output=True,
                    timeout=timeout_seconds,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                stdout_text = completed.stdout
                stderr_text = completed.stderr
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                raise ToolError(f"Code did not finish within {timeout_seconds:g} seconds.") from None

        # Preserve any generated data files (e.g. from pandas.to_csv/to_excel) into data/
        if returncode == 0:
            try:
                for fname in os.listdir(workdir):
                    fpath = os.path.join(workdir, fname)
                    if os.path.isfile(fpath):
                        os.makedirs(DATA_DIR, exist_ok=True)
                        dest = os.path.join(DATA_DIR, fname)
                        shutil.copy2(fpath, dest)
                        generated_files.append((fname, os.path.getsize(dest)))
            except Exception:
                pass

    out = stdout_text[:MAX_OUTPUT_CHARS]
    if returncode != 0:
        err = stderr_text.strip()[-1_500:]  # the end has the error
        raise ToolError(f"Code failed (exit code {returncode}):\n{err}")

    if generated_files:
        notes = "\n".join(f"[Saved data file: data/{fn} ({sz} bytes)]" for fn, sz in generated_files)
        out = (out.strip() + "\n" + notes).strip()

    return out if out.strip() else "(no output - use print() to show results)"


class PythonExecInput(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=5_000,
        description="Python 3 code for data processing or reporting. "
        "Output results with print() or save tables with pandas (e.g. df.to_csv('report.csv')). "
        "Do NOT call open() directly. "
        f"Allowed imports: {', '.join(sorted(ALLOWED_MODULES))}.",
    )


class PythonExecTool(AgentTool):
    name = "python_exec"
    input_model = PythonExecInput

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    async def run(self, args: PythonExecInput) -> str:  # type: ignore[override]
        problems = check_code_safety(args.code)
        if problems:
            raise ToolError("Code rejected by safety check:\n- " + "\n- ".join(problems))
        return await run_python(args.code, self._timeout)
