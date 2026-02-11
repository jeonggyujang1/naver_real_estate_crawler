"""make listing article_no bigint

Revision ID: 20260211_0003
Revises: 20260211_0002
Create Date: 2026-02-11 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260211_0003"
down_revision = "20260211_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "listing_snapshots",
        "article_no",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="article_no::bigint",
    )


def downgrade() -> None:
    op.alter_column(
        "listing_snapshots",
        "article_no",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="article_no::integer",
    )
