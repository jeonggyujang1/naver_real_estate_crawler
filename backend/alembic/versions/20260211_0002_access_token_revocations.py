"""add access token revocations

Revision ID: 20260211_0002
Revises: 20260210_0001
Create Date: 2026-02-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260211_0002"
down_revision = "20260210_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_access_token_revocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_access_jti"),
    )
    op.create_index(
        "ix_auth_access_token_revocations_jti",
        "auth_access_token_revocations",
        ["jti"],
        unique=False,
    )
    op.create_index(
        "ix_auth_access_token_revocations_expires_at",
        "auth_access_token_revocations",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_access_token_revocations_expires_at", table_name="auth_access_token_revocations")
    op.drop_index("ix_auth_access_token_revocations_jti", table_name="auth_access_token_revocations")
    op.drop_table("auth_access_token_revocations")
