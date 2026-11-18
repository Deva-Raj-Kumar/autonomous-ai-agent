"""Migration tests: Alembic must build exactly the schema the models describe.

SQLite tests run always (a temporary file). The MySQL test is opt-in, because it needs
your MySQL server: it creates a SCRATCH database, migrates it, round-trips data, and
drops it. Your real database is never touched.
    PowerShell:  $env:RUN_MYSQL_TESTS="1"; pytest -m mysql -v; Remove-Item Env:RUN_MYSQL_TESTS
    CI:          MYSQL_TEST_URL=mysql+pymysql://root:root@127.0.0.1:3306/ci (a service container)
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text

from alembic import command
from app.database.connection import Database, _mysql_utc_session, open_database
from app.database.migrations import alembic_config, current_revision, head_revision
from app.database.models import Base

# add_index = the models declare an index that the migrations never created.
SCHEMA_CHANGES = {"add_table", "remove_table", "add_column", "remove_column", "modify_type", "modify_nullable",
                  "add_index"}


def config_for(url: str):
    cfg = alembic_config(url)
    cfg.attributes["configure_logging"] = False
    return cfg


def schema_differences(url: str) -> list:
    engine = create_engine(url)
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    engine.dispose()
    flat = [d for item in diffs for d in (item if isinstance(item, list) else [item])]
    return [d for d in flat if d[0] in SCHEMA_CHANGES]


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"


def test_migrations_build_exactly_the_model_schema(sqlite_url: str) -> None:
    command.upgrade(config_for(sqlite_url), "head")

    assert schema_differences(sqlite_url) == []  # models and migrations agree


def test_migrations_can_be_undone_and_redone(sqlite_url: str) -> None:
    cfg = config_for(sqlite_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    tables_after_downgrade = set(inspect(create_engine(sqlite_url)).get_table_names())
    command.upgrade(cfg, "head")

    assert tables_after_downgrade <= {"alembic_version"}
    assert schema_differences(sqlite_url) == []


def test_baseline_reproduces_the_original_hand_made_tables(sqlite_url: str) -> None:
    command.upgrade(config_for(sqlite_url), "0001")

    tables = set(inspect(create_engine(sqlite_url)).get_table_names()) - {"alembic_version"}
    assert tables == {"users", "conversations", "memories", "tasks", "task_steps", "tool_logs", "approvals"}


def test_migration_creates_the_local_user(sqlite_url: str) -> None:
    command.upgrade(config_for(sqlite_url), "head")

    with create_engine(sqlite_url).connect() as conn:
        user = conn.execute(text("SELECT username, password_hash FROM users WHERE email='local@localhost'")).one()
    assert tuple(user) == ("local", "!")


def test_downgrade_keeps_the_local_user_while_it_owns_data(sqlite_url: str) -> None:
    cfg = config_for(sqlite_url)
    command.upgrade(cfg, "head")
    engine = create_engine(sqlite_url)
    with engine.begin() as conn:
        user_id = conn.execute(text("SELECT id FROM users WHERE email='local@localhost'")).scalar()
        conn.execute(text("INSERT INTO tasks (user_id, goal) VALUES (:u, 'kept')"), {"u": user_id})

    command.downgrade(cfg, "0001")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users WHERE email='local@localhost'")).scalar() == 1
        assert conn.execute(text("SELECT goal FROM tasks")).scalar() == "kept"


def test_unmigrated_database_is_refused(sqlite_url: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        database = open_database(sqlite_url)

    assert database is None
    assert "alembic upgrade head" in caplog.text


def test_auto_migrate_brings_the_schema_to_head(sqlite_url: str) -> None:
    database = open_database(sqlite_url, auto_migrate=True)

    assert database is not None
    assert current_revision(database.engine) == head_revision() == "0004"


def test_in_memory_database_uses_the_models() -> None:
    database = open_database("sqlite://")

    assert database is not None and "tasks" in inspect(database.engine).get_table_names()


def test_mysql_connections_are_pinned_to_utc() -> None:
    database = Database("mysql+pymysql://user:pw@localhost:3306/x")  # no connection is made here

    assert event.contains(database.engine, "connect", _mysql_utc_session)
    assert database.engine.pool._pre_ping is True


# ----------------------------------------------------------- real MySQL (opt-in)
@pytest.mark.mysql
@pytest.mark.skipif(os.getenv("RUN_MYSQL_TESTS") != "1", reason="set RUN_MYSQL_TESTS=1 to run")
def test_mysql_scratch_database_round_trip() -> None:
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    from app.config import BASE_DIR

    # CI passes a throwaway server's URL in MYSQL_TEST_URL; locally, .env's DATABASE_URL.
    real_url = os.getenv("MYSQL_TEST_URL") or dotenv_values(BASE_DIR / ".env").get("DATABASE_URL", "")
    if not real_url.startswith("mysql"):
        pytest.skip("no MySQL URL (set MYSQL_TEST_URL, or DATABASE_URL in .env)")
    scratch = make_url(real_url).set(database="autonomous_agent_test_scratch")
    server = create_engine(make_url(real_url).set(database=None))
    with server.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS autonomous_agent_test_scratch"))
        c.execute(text("CREATE DATABASE autonomous_agent_test_scratch CHARACTER SET utf8mb4"))
    try:
        url = scratch.render_as_string(hide_password=False)
        cfg = config_for(url)
        command.upgrade(cfg, "head")
        assert schema_differences(url) == []

        database = Database(url)
        user_id = database.default_user_id()
        with database.engine.connect() as conn:
            conn.execute(text("INSERT INTO tasks (user_id, goal, run_id) VALUES (:u, 'g', 'r1')"), {"u": user_id})
            conn.commit()
            stored = conn.execute(text("SELECT created_at FROM tasks WHERE run_id='r1'")).scalar()
        # Stored by the DB default in the UTC session: within a minute of real UTC time.
        assert abs((stored.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()) < 60
        database.dispose()

        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        assert schema_differences(url) == []
    finally:
        with server.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS autonomous_agent_test_scratch"))
