"""add billing foundation tables

Revision ID: 20260213_0004
Revises: 20260211_0003
Create Date: 2026-02-13 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260213_0004"
down_revision = "20260211_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_subscriptions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.String(length=20), nullable=False, server_default=sa.text("'FREE'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default=sa.text("'dummy'")),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_user_subscriptions_plan_code", "user_subscriptions", ["plan_code"], unique=False)
    op.create_index("ix_user_subscriptions_status", "user_subscriptions", ["status"], unique=False)

    op.create_table(
        "billing_checkout_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default=sa.text("'dummy'")),
        sa.Column("plan_code", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("checkout_token", sa.String(length=80), nullable=False),
        sa.Column("amount_krw", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default=sa.text("'KRW'")),
        sa.Column(
            "checkout_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkout_token", name="uq_billing_checkout_token"),
    )
    op.create_index("ix_billing_checkout_sessions_status", "billing_checkout_sessions", ["status"], unique=False)
    op.create_index("ix_billing_checkout_sessions_user_id", "billing_checkout_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_billing_checkout_sessions_user_id", table_name="billing_checkout_sessions")
    op.drop_index("ix_billing_checkout_sessions_status", table_name="billing_checkout_sessions")
    op.drop_table("billing_checkout_sessions")

    op.drop_index("ix_user_subscriptions_status", table_name="user_subscriptions")
    op.drop_index("ix_user_subscriptions_plan_code", table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
