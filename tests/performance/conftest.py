"""Performance tests use the full-stack harness on an Alembic-MIGRATED database, so
indexes are exactly the production ones (create_all could hide a missing index)."""

from tests.support.stack import client, stack_env, start_app  # noqa: F401  (pytest fixtures)
