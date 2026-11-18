"""Tests for the safe calculator, including attempts to break out of it."""

import pytest

from app.tools.base import ToolError
from app.tools.calculator import format_number, safe_eval


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14),  # precedence: * before +
        ("(2 + 3) * 4", 20),
        ("(45000 + 52000) / 2", 48500),
        ("7 // 2", 3),
        ("7 % 3", 1),
        ("2 ** 10", 1024),
        ("-5 + +3", -2),
        ("sqrt(16) * 3", 12),
        ("max(3, 9, 4) - min(3, 9, 4)", 6),
        ("round(pi, 2)", 3.14),
        ("abs(-7.5)", 7.5),
    ],
)
def test_valid_expressions(expression: str, expected: float) -> None:
    assert safe_eval(expression) == pytest.approx(expected)


def test_float_noise_is_hidden_when_formatting() -> None:
    assert format_number(safe_eval("0.1 + 0.2")) == "0.3"


@pytest.mark.parametrize(
    "attack",
    [
        "__import__('os').system('dir')",  # code execution
        "open('secret.txt').read()",  # file access
        "().__class__.__bases__",  # classic sandbox escape
        "x + 1",  # unknown variable
        "[1, 2, 3]",  # lists aren't math
        "'a' * 5",  # strings aren't math
        "True + 1",  # bools are rejected even though Python treats them as ints
        "lambda: 1",
    ],
)
def test_dangerous_or_non_math_input_is_rejected(attack: str) -> None:
    with pytest.raises(ToolError):
        safe_eval(attack)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("1 / 0", "Division by zero"),
        ("9 ** 9 ** 9", "too large"),  # would freeze the server without the guard
        ("2 ** 5000", "Exponent too large"),
        ("sqrt(-1)", "Math error"),
        ("2 +", "syntax"),
    ],
)
def test_errors_have_clear_messages(expression: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        safe_eval(expression)
