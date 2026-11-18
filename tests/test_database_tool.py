"""Database tool tests, using a throwaway in-memory SQLite database."""

import pytest

from app.database.connection import Database, DatabaseConfigError, open_database
from app.tools.base import ToolError
from app.tools.database_tool import DatabaseQueryTool, QueryInput, SaveInput, SaveToDatabaseTool

pytestmark = pytest.mark.anyio


@pytest.fixture
def db() -> Database:
    database = Database("sqlite://")  # "sqlite://" = in-memory, gone after the test
    database.create_tables()
    return database


async def save(db: Database, kind: str, title: str, content: str) -> str:
    return await SaveToDatabaseTool(db).run(SaveInput(kind=kind, title=title, content=content))


async def query(db: Database, **kwargs) -> str:
    return await DatabaseQueryTool(db).run(QueryInput(**kwargs))


async def test_save_returns_new_id(db: Database) -> None:
    assert await save(db, "report", "Jobs report", "Python is common") == (
        "Saved report #1: 'Jobs report' (16 characters)."
    )


async def test_query_by_keyword_is_case_insensitive(db: Database) -> None:
    await save(db, "report", "Bengaluru jobs", "Python, SQL")
    await save(db, "note", "Groceries", "milk")

    output = await query(db, keyword="PYTHON")

    assert "Bengaluru jobs" in output
    assert "Groceries" not in output
    assert output.startswith("<untrusted_data")


async def test_query_by_kind(db: Database) -> None:
    await save(db, "report", "R1", "a")
    await save(db, "note", "N1", "b")

    output = await query(db, kind="note")

    assert "N1" in output and "R1" not in output


async def test_query_by_id_returns_full_content(db: Database) -> None:
    await save(db, "research", "Long one", "word " * 200)

    output = await query(db, record_id=1)

    assert output.count("word") == 200  # full text, not the 300-character preview


async def test_missing_id_is_a_tool_error(db: Database) -> None:
    with pytest.raises(ToolError, match="No saved record with id 99"):
        await query(db, record_id=99)


async def test_wildcard_characters_are_literal(db: Database) -> None:
    await save(db, "note", "Discount", "50% off")
    await save(db, "note", "Other", "nothing here")

    output = await query(db, keyword="%")  # would match EVERYTHING if not escaped

    assert "Discount" in output and "Other" not in output


async def test_sql_injection_text_is_just_data(db: Database) -> None:
    await save(db, "note", "x'; DROP TABLE saved_records; --", "harmless")

    output = await query(db, keyword="drop table")

    assert "DROP TABLE" in output  # stored and found as plain text; the table still exists


def test_invalid_url_error_never_shows_the_password() -> None:
    bad_url = 'f"mysql+pymysql://root:Sup3r@Secret@:localhost:3306/db'

    with pytest.raises(DatabaseConfigError) as exc_info:
        Database(bad_url)

    assert "Sup3r" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None  # original exception (with the URL) is dropped


def test_open_database_returns_none_on_bad_url(caplog: pytest.LogCaptureFixture) -> None:
    assert open_database("not a url at all") is None
    assert "Database disabled" in caplog.text
