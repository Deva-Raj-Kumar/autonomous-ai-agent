"""Small, safe tools for learning function calling.

Phase 4 builds the real tool system (registry, permissions, timeouts) in app/tools/.
These three are enough to see the full loop: the model asks for a tool, we run it,
and we send the result back.

The @tool decorator turns a normal function into a LangChain tool:
  - name        = function name
  - description = docstring (the model reads this to decide WHEN to use the tool)
  - arguments   = type hints, converted to a JSON schema and validated by Pydantic
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


@tool
def get_current_time(timezone: str = "Asia/Kolkata") -> str:
    """Get the current date and time in an IANA timezone such as 'Asia/Kolkata' or 'UTC'."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        # Return the error as text: the model can read it and try again with a valid name.
        return f"Error: unknown timezone '{timezone}'. Use an IANA name like 'Asia/Kolkata'."
    return now.strftime("%A, %d %B %Y, %H:%M:%S %Z")


@tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


@tool
def multiply_numbers(a: float, b: float) -> float:
    """Multiply two numbers and return the product."""
    return a * b


EXAMPLE_TOOLS = [get_current_time, add_numbers, multiply_numbers]
