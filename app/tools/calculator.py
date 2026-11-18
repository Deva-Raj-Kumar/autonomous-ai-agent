"""Safe calculator.

NEVER use eval() on text from an LLM or a user: eval("__import__('os').system('...')")
runs any command. Instead we parse the expression into a syntax tree (AST) and only
evaluate node types we explicitly allow: numbers, + - * / // % **, parentheses,
a few math functions and constants. Anything else is rejected.
"""

import ast
import math
import operator
import warnings
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import AgentTool, ToolError

MAX_EXPONENT = 1_000
MAX_RESULT_DIGITS = 1_000  # refuse results like 9**9**9 that would take forever to compute


def _safe_pow(base: float, exponent: float) -> float:
    if abs(exponent) > MAX_EXPONENT:
        raise ToolError(f"Exponent too large (max {MAX_EXPONENT}).")
    if abs(base) > 1 and abs(exponent) * math.log10(abs(base)) > MAX_RESULT_DIGITS:
        raise ToolError("Result would be too large.")
    return operator.pow(base, exponent)


_BINARY_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _safe_pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def safe_eval(expression: str) -> int | float:
    """Evaluate a math expression using only allowed operations."""
    try:
        # Odd input like "1if" makes the parser emit a SyntaxWarning: user input must not
        # be able to write noise into the server log, so those warnings are muted here.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(expression.strip(), mode="eval")  # "eval" mode = one expression only
    except SyntaxError as exc:
        raise ToolError(f"Invalid expression syntax: {exc.msg}.") from exc
    try:
        return _evaluate(tree.body)
    except ZeroDivisionError as exc:
        raise ToolError("Division by zero.") from exc
    except OverflowError as exc:
        raise ToolError("Result is too large.") from exc
    except (ValueError, TypeError) as exc:  # e.g. sqrt(-1), max() with no arguments
        raise ToolError(f"Math error: {exc}.") from exc


def _evaluate(node: ast.AST) -> Any:
    """Walk the syntax tree recursively. `match` checks each node's type and shape."""
    match node:
        case ast.Constant(value=value) if type(value) in (int, float):  # bool is excluded
            return value
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY_OPS:
            return _BINARY_OPS[type(op)](_evaluate(left), _evaluate(right))
        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY_OPS:
            return _UNARY_OPS[type(op)](_evaluate(operand))
        case ast.Name(id=name) if name in _CONSTANTS:
            return _CONSTANTS[name]
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _FUNCTIONS:
            return _FUNCTIONS[name](*(_evaluate(arg) for arg in args))
    raise ToolError(f"Not allowed in a calculation: {ast.unparse(node)!r}.")


def format_number(value: int | float) -> str:
    """0.1 + 0.2 gives 0.30000000000000004 in floating point; show it as 0.3."""
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


class CalculatorInput(BaseModel):
    expression: str = Field(
        min_length=1,
        max_length=200,
        description="A math expression, e.g. '(45000 + 52000) / 2' or 'sqrt(16) * 3'. "
        "Supports + - * / // % **, parentheses, sqrt, log, log10, exp, sin, cos, tan, "
        "floor, ceil, abs, round, min, max, pi, e.",
    )


class CalculatorTool(AgentTool):
    name = "calculator"
    input_model = CalculatorInput

    async def run(self, args: CalculatorInput) -> str:  # type: ignore[override]
        return f"{args.expression} = {format_number(safe_eval(args.expression))}"
