"""Authentication (Phase 12).

  users          + is_admin, last_login_at
  NEW TABLE      refresh_tokens (SHA-256 hashes only; rotation + reuse detection)
  conversations  session ids unique PER USER instead of across the whole table
                 (two users may both name a session "default")

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("users") as t:
        t.add_column(sa.Column("is_admin", sa.Boolean(), server_default="0", nullable=False))
        t.add_column(sa.Column("last_login_at", sa.TIMESTAMP(), nullable=True))

    op.create_table(
        "refresh_tokens",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("user_id", ID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    # Create the new constraint BEFORE dropping the old one: the table is never
    # left without a uniqueness guarantee.
    with op.batch_alter_table("conversations") as t:
        t.create_unique_constraint("uq_conversations_user_session", ["user_id", "session_key"])
        t.drop_constraint("uq_conversations_session_key", type_="unique")


def downgrade() -> None:
    # NOTE: fails if two users now share a session id; resolve those rows first.
    # MySQL: the foreign key on conversations.user_id needs an index starting with
    # user_id. When upgrade() added (user_id, session_key), MySQL silently dropped its
    # automatic FK index because the new one could serve the FK. So give the FK its own
    # index BEFORE dropping the composite one (error 1553 otherwise). It stays afterwards.
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    with op.batch_alter_table("conversations") as t:
        t.create_unique_constraint("uq_conversations_session_key", ["session_key"])
        t.drop_constraint("uq_conversations_user_session", type_="unique")
    # Dropping the table drops its indexes too. (Dropping ix_refresh_tokens_user_id first
    # would fail on MySQL: the foreign key still needs it.)
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("users") as t:
        t.drop_column("last_login_at")
        t.drop_column("is_admin")
