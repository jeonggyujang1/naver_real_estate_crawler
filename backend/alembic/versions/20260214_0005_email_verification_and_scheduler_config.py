"""add email verification and scheduler config tables

Revision ID: 20260214_0005
Revises: 20260213_0004
Create Date: 2026-02-14 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260214_0005"
down_revision = "20260213_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "auth_email_verification_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_token_hash"),
    )
    op.create_index(
        "ix_auth_email_verification_tokens_token_hash",
        "auth_email_verification_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        "ix_auth_email_verification_tokens_user_id",
        "auth_email_verification_tokens",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "scheduler_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'Asia/Seoul'")),
        sa.Column("times_csv", sa.String(length=255), nullable=False, server_default=sa.text("'09:00,18:00'")),
        sa.Column("poll_seconds", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("reuse_bucket_hours", sa.Integer(), nullable=False, server_default=sa.text("12")),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduler_configs_updated_by_user_id", "scheduler_configs", ["updated_by_user_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO scheduler_configs (id, enabled, timezone, times_csv, poll_seconds, reuse_bucket_hours)
            VALUES (1, false, 'Asia/Seoul', '09:00,18:00', 20, 12)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_configs_updated_by_user_id", table_name="scheduler_configs")
    op.drop_table("scheduler_configs")

    op.drop_index("ix_auth_email_verification_tokens_user_id", table_name="auth_email_verification_tokens")
    op.drop_index("ix_auth_email_verification_tokens_token_hash", table_name="auth_email_verification_tokens")
    op.drop_table("auth_email_verification_tokens")

    op.drop_column("users", "email_verified")
