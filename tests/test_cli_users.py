"""CLI account administration. getpass is patched (no real typing) and the database is
in-memory SQLite."""

from unittest.mock import patch

import pytest

from app import cli
from app.auth.context import acting_as
from app.database.connection import Database
from app.database.crud import RunRepository
from app.database.models import User

pytestmark = pytest.mark.anyio
PASSWORD = "correct horse battery staple"


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Database:
    db = Database("sqlite://")
    db.create_tables()
    monkeypatch.setattr(cli, "require_database", lambda: db)
    return db


async def test_create_admin_and_adopt_the_local_data(database: Database, capsys: pytest.CaptureFixture) -> None:
    await RunRepository(database).create_run("cli-run", "made in the CLI")  # owned by the local user

    with patch("getpass.getpass", side_effect=[PASSWORD, PASSWORD]) as typed:
        await cli.users_command(["create", "Asha@Example.com", "asha"], make_admin=True, adopt_local=True)

    assert typed.call_count == 2  # asked twice, never taken from the command line
    out = capsys.readouterr().out
    assert "(admin)" in out and "tasks 1" in out and PASSWORD not in out
    with database.session() as s:
        asha = s.query(User).filter_by(email="asha@example.com").one()
    with acting_as(asha.id):
        assert await RunRepository(database).is_mine("cli-run")


async def test_mismatched_or_weak_passwords_are_refused(database: Database) -> None:
    with patch("getpass.getpass", side_effect=[PASSWORD, "something else entirely"]):
        with pytest.raises(SystemExit, match="don't match"):
            await cli.users_command(["create", "a@example.com", "asha"], make_admin=False, adopt_local=False)
    with patch("getpass.getpass", side_effect=["password123", "password123"]):
        with pytest.raises(SystemExit, match="too easy"):
            await cli.users_command(["create", "a@example.com", "asha"], make_admin=False, adopt_local=False)


async def test_disable_and_list(database: Database, capsys: pytest.CaptureFixture) -> None:
    with patch("getpass.getpass", side_effect=[PASSWORD, PASSWORD]):
        await cli.users_command(["create", "ravi@example.com", "ravi"], make_admin=False, adopt_local=False)

    await cli.users_command(["disable", "ravi@example.com"], make_admin=False, adopt_local=False)
    await cli.users_command(["list"], make_admin=False, adopt_local=False)

    last_line = capsys.readouterr().out.splitlines()[-1]
    assert "ravi@example.com" in last_line and "disabled" in last_line
    with pytest.raises(SystemExit, match="No user"):
        await cli.users_command(["promote", "nobody@example.com"], make_admin=False, adopt_local=False)
