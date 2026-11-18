"""Agent extensions: ONLY additions to the original design; nothing is removed or renamed.

  conversations  + session_key (the API's session id), summary, updated_at
  memories       + importance, source, created_at, updated_at, last_accessed_at, access_count
  tasks          + run_id (LangGraph thread id), final_output, steps_used, quality_score, error, updated_at
  task_steps     + step_key ("t1"), title, attempts, error
  tool_logs      + step_key, attempt, error, created_at
  approvals      + step_key, arguments_hash (SHA-256), requested_at, decided_by
  NEW TABLE      conversation_messages (chat history)
  NEW TABLE      saved_records (save_to_database / database_query tools)
  DATA           the default local user, owner of all data until Phase 12 adds logins

batch_alter_table: SQLite can't ALTER most things, so Alembic rebuilds the table there;
on MySQL it emits normal ALTER TABLE statements.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
LONG_TEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamp(name: str, *, default_now: bool = True) -> sa.Column:
    return sa.Column(name, sa.TIMESTAMP(), server_default=NOW if default_now else None, nullable=True)


def upgrade() -> None:
    with op.batch_alter_table("conversations") as t:
        # NOT NULL without a default is safe here: the original tables were empty.
        t.add_column(sa.Column("session_key", sa.String(64), nullable=False))
        t.add_column(sa.Column("summary", sa.Text()))
        t.add_column(timestamp("updated_at"))
        t.create_unique_constraint("uq_conversations_session_key", ["session_key"])

    with op.batch_alter_table("memories") as t:
        t.add_column(sa.Column("importance", sa.Integer(), nullable=False, server_default="3"))
        t.add_column(sa.Column("source", sa.String(100)))
        t.add_column(timestamp("created_at"))
        t.add_column(timestamp("updated_at"))
        t.add_column(timestamp("last_accessed_at", default_now=False))
        t.add_column(sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("tasks") as t:
        t.add_column(sa.Column("run_id", sa.String(64)))
        t.add_column(sa.Column("final_output", LONG_TEXT))
        t.add_column(sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"))
        t.add_column(sa.Column("quality_score", sa.Float()))
        t.add_column(sa.Column("error", sa.Text()))
        t.add_column(timestamp("updated_at"))
        t.create_unique_constraint("uq_tasks_run_id", ["run_id"])

    with op.batch_alter_table("task_steps") as t:
        t.add_column(sa.Column("step_key", sa.String(20)))
        t.add_column(sa.Column("title", sa.String(200)))
        t.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        t.add_column(sa.Column("error", sa.Text()))

    with op.batch_alter_table("tool_logs") as t:
        t.add_column(sa.Column("step_key", sa.String(20)))
        t.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        t.add_column(sa.Column("error", sa.Text()))
        t.add_column(timestamp("created_at"))

    with op.batch_alter_table("approvals") as t:
        t.add_column(sa.Column("step_key", sa.String(20)))
        t.add_column(sa.Column("arguments_hash", sa.String(64)))
        t.add_column(timestamp("requested_at"))
        t.add_column(sa.Column("decided_by", sa.String(100)))

    op.create_table(
        "conversation_messages",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", ID, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", LONG_TEXT, nullable=False),
        sa.Column("summarized", sa.Boolean(), nullable=False, server_default="0"),
        timestamp("created_at"),
    )
    op.create_table(
        "saved_records",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("user_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", LONG_TEXT, nullable=False),
        timestamp("created_at"),
    )
    op.create_index("ix_saved_records_kind", "saved_records", ["kind"])

    # The default local user. "!" can never match a password hash: nobody can log in as it.
    op.execute(
        "INSERT INTO users (username, email, password_hash, is_active) "
        "VALUES ('local', 'local@localhost', '!', 1)"
    )


def downgrade() -> None:
    op.drop_index("ix_saved_records_kind", table_name="saved_records")
    op.drop_table("saved_records")
    # Remove the local user ONLY if nothing still belongs to it. Rows in the original
    # tables (tasks, memories, conversations) survive a downgrade, and deleting their
    # owner would either fail (foreign keys) or orphan real data.
    op.execute(
        "DELETE FROM users WHERE email = 'local@localhost'"
        " AND NOT EXISTS (SELECT 1 FROM tasks WHERE tasks.user_id = users.id)"
        " AND NOT EXISTS (SELECT 1 FROM memories WHERE memories.user_id = users.id)"
        " AND NOT EXISTS (SELECT 1 FROM conversations WHERE conversations.user_id = users.id)"
    )
    op.drop_table("conversation_messages")
    with op.batch_alter_table("approvals") as t:
        for column in ("decided_by", "requested_at", "arguments_hash", "step_key"):
            t.drop_column(column)
    with op.batch_alter_table("tool_logs") as t:
        for column in ("created_at", "error", "attempt", "step_key"):
            t.drop_column(column)
    with op.batch_alter_table("task_steps") as t:
        for column in ("error", "attempts", "title", "step_key"):
            t.drop_column(column)
    with op.batch_alter_table("tasks") as t:
        t.drop_constraint("uq_tasks_run_id", type_="unique")
        for column in ("updated_at", "error", "quality_score", "steps_used", "final_output", "run_id"):
            t.drop_column(column)
    with op.batch_alter_table("memories") as t:
        for column in ("access_count", "last_accessed_at", "updated_at", "created_at", "source", "importance"):
            t.drop_column(column)
    with op.batch_alter_table("conversations") as t:
        t.drop_constraint("uq_conversations_session_key", type_="unique")
        for column in ("updated_at", "summary", "session_key"):
            t.drop_column(column)
