"""Database connection: one engine (connection pool) + a session factory.

Engine  = knows how to talk to the database and keeps a pool of connections.
Session = one "unit of work": you add/query objects, then commit or roll back together.

WHO CREATES THE TABLES? (Phase 11)
  - Real databases (MySQL, a SQLite file, PostgreSQL): ALEMBIC MIGRATIONS only
    (`alembic upgrade head`). Migrations are versioned scripts in git, so every machine
    gets exactly the same schema, and changes are reviewed like code.
  - In-memory SQLite ("sqlite://", used by the tests): create_all() from the models.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Base, User

logger = logging.getLogger(__name__)

LOCAL_USER_EMAIL = "local@localhost"  # the default owner of all data until Phase 12 adds logins


class NotAuthenticatedError(RuntimeError):
    """Data was accessed in API mode without a logged-in user: a programming error
    (an endpoint forgot the auth dependency), so it fails loudly, never leaks."""


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL is invalid or its driver is missing. Messages never include the URL,
    because URLs often contain a password."""


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        try:
            parsed = make_url(url)
        except ArgumentError:
            # `from None` drops the original exception, so the URL can't leak into tracebacks.
            raise DatabaseConfigError(
                "DATABASE_URL is not a valid SQLAlchemy URL. Check it in .env "
                "(special characters in passwords must be URL-encoded, e.g. @ -> %40)."
            ) from None

        kwargs: dict = {"echo": echo}  # echo=True prints every SQL statement (debugging)
        if parsed.drivername.startswith("sqlite"):
            # Tools run DB work in worker threads; SQLite must allow that.
            kwargs["connect_args"] = {"check_same_thread": False}
            if parsed.database in (None, "", ":memory:"):
                # In-memory DB: share ONE connection, or each thread would get an empty DB.
                kwargs["poolclass"] = StaticPool
            else:
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        else:
            # Server databases close idle connections (MySQL wait_timeout). pre_ping tests
            # a pooled connection before use; recycle replaces it after an hour.
            kwargs |= {"pool_pre_ping": True, "pool_recycle": 3600}

        try:
            self.engine: Engine = create_engine(parsed, **kwargs)
        except (NoSuchModuleError, ModuleNotFoundError) as exc:
            raise DatabaseConfigError(
                f"Database driver for '{parsed.drivername}' is not installed ({exc})."
            ) from None

        self.dialect = parsed.get_backend_name()  # "sqlite", "mysql", "postgresql"
        self.in_memory = self.dialect == "sqlite" and parsed.database in (None, "", ":memory:")
        self.url = parsed
        if self.dialect == "mysql":
            event.listen(self.engine, "connect", _mysql_utc_session)

        # expire_on_commit=False: objects stay readable after the session closes.
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self._default_user_id: int | None = None
        # API mode sets this to True: data access WITHOUT an authenticated user raises,
        # instead of silently acting as the local user (fail closed).
        self.require_login = False

    def create_tables(self) -> None:
        """Create tables from the models. ONLY for throwaway databases (tests);
        real databases get their schema from Alembic migrations."""
        Base.metadata.create_all(self.engine)
        from app.database.email_models import EmailBase
        EmailBase.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """`with db.session() as s:` commits on success and rolls back on any error."""
        with self._session_factory() as session, session.begin():
            yield session

    def default_user_id(self) -> int:
        """Id of the local user that owns all data until Phase 12 adds logins.
        Migration 0002 creates it; created here too for throwaway test databases."""
        if self._default_user_id is None:
            with self.session() as s:
                user_id = s.scalar(select(User.id).where(User.email == LOCAL_USER_EMAIL))
                if user_id is None:
                    user = User(username="local", email=LOCAL_USER_EMAIL, password_hash="!", is_active=True)  # noqa: S106  # nosec B106 - "!" = no usable password
                    s.add(user)
                    s.flush()
                    user_id = user.id
            self._default_user_id = user_id
        return self._default_user_id

    def ping(self) -> bool:
        """Can we reach the database right now? (readiness checks)"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def current_user_id(self) -> int:
        """Owner for every read/write: the logged-in user of this request or background
        run. Without one: the local user (CLI), or an error when logins are required."""
        from app.auth.context import current_user_id

        user_id = current_user_id()
        if user_id is not None:
            return user_id
        if self.require_login:
            raise NotAuthenticatedError("No authenticated user for this operation.")
        return self.default_user_id()

    def dispose(self) -> None:
        """Close all pooled connections (on shutdown)."""
        self.engine.dispose()


def _mysql_utc_session(dbapi_connection, _record) -> None:
    """MySQL converts TIMESTAMP values to the SESSION time zone. A server in India runs at
    +05:30, which would shift every stored time. Pinning each connection to UTC keeps all
    reads and writes in UTC."""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.close()


def open_database(url: str, *, auto_migrate: bool = False) -> Database | None:
    """Open the database, or return None (with a warning) on failure.

    In-memory SQLite gets tables from the models. Any other database must already be
    migrated to the latest Alembic revision; with auto_migrate=True it is upgraded here.
    Only error TYPES are logged for connection failures: driver messages can include
    connection details.
    """
    from app.database.migrations import current_revision, head_revision, upgrade_to_head

    try:
        database = Database(url)
        if database.in_memory:
            database.create_tables()
            return database
        current, head = current_revision(database.engine), head_revision()
        if current != head:
            if not auto_migrate:
                logger.warning(
                    "Database disabled: schema is at revision %s but the code needs %s. "
                    "Run:  alembic upgrade head   (or set DB_AUTO_MIGRATE=true)", current, head,
                )
                database.dispose()
                return None
            logger.info("Migrating database schema %s -> %s", current, head)
            upgrade_to_head(url)
        from app.database.email_models import EmailBase
        EmailBase.metadata.create_all(database.engine)
        return database
    except DatabaseConfigError as exc:
        logger.warning("Database disabled: %s", exc)
    except SQLAlchemyError as exc:
        logger.warning("Database disabled: could not connect (%s).", type(exc).__name__)
    return None
