"""Initial schema: the hand-made MySQL design (users, conversations, memories, tasks,
task_steps, tool_logs, approvals), reproduced exactly (see docs/db/original_schema.sql).

On the ORIGINAL database these tables already existed, so this revision was only
*stamped* (`alembic stamp 0001`: recorded as applied without running). On any NEW
database (a teammate's machine, Docker, CI) it creates the tables.

Revision ID: 0001
Revises: (none)
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# BIGINT ids (as designed). SQLite only auto-increments INTEGER primary keys.
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("'1'")),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=NOW, nullable=True),
        sa.UniqueConstraint("email", name="email"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("user_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("status", sa.String(30), server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=NOW, nullable=True),
    )
    op.create_table(
        "memories",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("user_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("memory_type", sa.String(50)),
        sa.Column("memory_content", sa.Text().with_variant(mysql.LONGTEXT(), "mysql")),
        sa.Column("metadata", sa.JSON()),
    )
    op.create_table(
        "tasks",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("user_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", ID, sa.ForeignKey("conversations.id")),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), server_default="pending"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=NOW, nullable=True),
    )
    op.create_table(
        "task_steps",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("tool_name", sa.String(100)),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("result", sa.JSON()),
        sa.UniqueConstraint("task_id", "step_number", name="task_id"),
    )
    op.create_table(
        "tool_logs",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("tool_name", sa.String(100)),
        sa.Column("input_data", sa.JSON()),
        sa.Column("output_data", sa.JSON()),
        sa.Column("status", sa.String(30)),
        sa.Column("execution_time_ms", sa.Integer()),
    )
    op.create_table(
        "approvals",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("action_name", sa.String(100)),
        sa.Column("action_details", sa.JSON()),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("approved_at", sa.TIMESTAMP(), nullable=True),
    )


def downgrade() -> None:
    for table in ("approvals", "tool_logs", "task_steps", "tasks", "memories", "conversations", "users"):
        op.drop_table(table)
