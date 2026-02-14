"""add user trade preference and conversion override fields

Revision ID: 20260214_0006
Revises: 20260214_0005
Create Date: 2026-02-14 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260214_0006"
down_revision = "20260214_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_notification_settings",
        sa.Column(
            "interest_trade_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'ALL'"),
        ),
    )
    op.add_column(
        "user_notification_settings",
        sa.Column("monthly_rent_conversion_rate_pct", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_notification_settings", "monthly_rent_conversion_rate_pct")
    op.drop_column("user_notification_settings", "interest_trade_type")
