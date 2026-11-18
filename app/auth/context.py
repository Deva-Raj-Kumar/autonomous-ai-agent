"""WHO is the current request acting for?

A ContextVar is a variable with one value per asyncio task (per request, per background
run). FastAPI sets it once, in the auth dependency; the data stores read it through
Database.current_user_id(). That keeps user_id out of hundreds of function signatures,
and it follows the work automatically:
  - asyncio.create_task() copies the context: a background run keeps its owner;
  - asyncio.to_thread() copies it too: the SQLAlchemy code in worker threads sees it.

Trade-off: it's implicit. So the API side FAILS CLOSED: if nothing set a user, the
database raises instead of quietly using someone (see Database.require_login).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def current_user_id() -> int | None:
    return _current_user_id.get()


def bind_user(user_id: int) -> None:
    """Set the user for the rest of THIS task (and tasks/threads it starts)."""
    _current_user_id.set(user_id)


@contextmanager
def acting_as(user_id: int) -> Iterator[None]:
    """Temporarily act as a user (CLI admin commands, tests)."""
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)
