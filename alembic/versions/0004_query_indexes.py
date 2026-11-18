"""Indexes for the queries the app actually runs (found by tests/performance).

MySQL silently creates an index for every foreign key, so on MySQL most of these
already "existed". SQLite and PostgreSQL do NOT: there, "my memories" or "this run's
tool logs" scanned the whole table. Explicit indexes make the schema fast everywhere.

  tasks                  (user_id, created_at)  newest runs per user, no sort step
  memories               (user_id)
  tool_logs              (task_id)
  approvals              (task_id)
  conversation_messages  (conversation_id)
  saved_records          (user_id)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_tasks_user_created", "tasks", ["user_id", "created_at"]),
    ("ix_memories_user_id", "memories", ["user_id"]),
    ("ix_tool_logs_task_id", "tool_logs", ["task_id"]),
    ("ix_approvals_task_id", "approvals", ["task_id"]),
    ("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]),
    ("ix_saved_records_user_id", "saved_records", ["user_id"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    # On MySQL these indexes now serve the foreign keys (MySQL dropped its automatic FK
    # indexes when they were created), so dropping them fails with error 1553. MySQL
    # would need an equivalent index anyway: keeping them IS the correct older state.
    if op.get_bind().dialect.name == "mysql":
        return
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
