"""Small helpers around Alembic, so the app and the tests can check/apply migrations
from Python (the CLI equivalent is `alembic current` / `alembic upgrade head`)."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def alembic_config(url: str | None = None) -> Config:
    """Alembic configuration. The database URL is NOT stored in alembic.ini (it holds a
    password): env.py reads it from the app settings, or from `url` given here."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    if url is not None:
        # Alembic's ini parser treats % as special: escape it (passwords may be %-encoded).
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def head_revision() -> str | None:
    """The newest migration in alembic/versions (what the code expects)."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    """The migration the database is at (None = never migrated)."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")
