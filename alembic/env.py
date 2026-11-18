"""Alembic environment: how migrations connect to the database.

Run from the project root:
    alembic upgrade head                         # apply all pending migrations
    alembic current                              # which revision is the database at?
    alembic revision --autogenerate -m "msg"     # draft a migration from model changes
    alembic downgrade -1                         # undo the last migration

The database URL comes from DATABASE_URL in .env (via the app settings), never from
alembic.ini, because the URL contains a password and alembic.ini is committed to git.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, event, pool

from alembic import context
from app.config import get_settings
from app.database.connection import _mysql_utc_session
from app.database.models import Base

config = context.config

# Use alembic.ini's logging setup only when run from the CLI (not inside the app/tests).
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The models' metadata: lets `--autogenerate` compare models with the real database.
target_metadata = Base.metadata


def database_url() -> str:
    # An explicit URL (from app.database.migrations.alembic_config) wins; otherwise .env.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Autogenerate filter. Indexes that exist only in the database are ignored: MySQL
    creates one automatically for every foreign key, and they aren't declared in the models."""
    if type_ == "index" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it (for review)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = database_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    if connectable.dialect.name == "mysql":
        # Same UTC rule as the app, set at DRIVER level when the connection opens.
        # Do NOT run `SET time_zone` on the connection below before context.configure():
        # in SQLAlchemy 2.x that statement silently opens a transaction, Alembic then
        # doesn't commit, and the migration is rolled back (found while testing on MySQL).
        event.listen(connectable, "connect", _mysql_utc_session)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # also detect column TYPE changes
            include_object=include_object,
            # SQLite can't ALTER most things: "batch" mode rebuilds the table instead.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
