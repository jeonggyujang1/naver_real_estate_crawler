"""initial schema

Revision ID: 20260210_0001
Revises:
Create Date: 2026-02-10 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260210_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("complex_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'SUCCESS'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_complex_no", "crawl_runs", ["complex_no"], unique=False)

    op.create_table(
        "user_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False, server_default=sa.text("'complex'")),
        sa.Column("filter_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chart_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_preset_name"),
    )

    op.create_table(
        "user_watch_complexes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("complex_no", sa.Integer(), nullable=False),
        sa.Column("complex_name", sa.String(length=255), nullable=True),
        sa.Column("sido_name", sa.String(length=100), nullable=True),
        sa.Column("gugun_name", sa.String(length=100), nullable=True),
        sa.Column("dong_name", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "complex_no", name="uq_user_complex"),
    )
    op.create_index("ix_user_watch_complexes_complex_no", "user_watch_complexes", ["complex_no"], unique=False)

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_refresh_jti"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )
    op.create_index("ix_auth_refresh_tokens_jti", "auth_refresh_tokens", ["jti"], unique=False)

    op.create_table(
        "user_notification_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_address", sa.String(length=255), nullable=True),
        sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("telegram_chat_id", sa.String(length=100), nullable=True),
        sa.Column("bargain_alert_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("bargain_lookback_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("bargain_discount_threshold", sa.Float(), nullable=False, server_default=sa.text("0.08")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "alert_dispatch_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("alert_type", sa.String(length=30), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel", "alert_type", "dedupe_key", name="uq_alert_dispatch_dedupe"),
    )
    op.create_index("ix_alert_dispatch_logs_alert_type", "alert_dispatch_logs", ["alert_type"], unique=False)

    op.create_table(
        "listing_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("crawl_run_id", sa.Integer(), nullable=False),
        sa.Column("complex_no", sa.Integer(), nullable=False),
        sa.Column("article_no", sa.Integer(), nullable=False),
        sa.Column("article_name", sa.String(length=255), nullable=True),
        sa.Column("trade_type_name", sa.String(length=30), nullable=True),
        sa.Column("deal_price_text", sa.String(length=50), nullable=True),
        sa.Column("rent_price_text", sa.String(length=50), nullable=True),
        sa.Column("deal_price_manwon", sa.Integer(), nullable=True),
        sa.Column("rent_price_manwon", sa.Integer(), nullable=True),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column("floor_info", sa.String(length=50), nullable=True),
        sa.Column("direction", sa.String(length=30), nullable=True),
        sa.Column("confirmed_date", sa.Date(), nullable=True),
        sa.Column("listing_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "article_no", name="uq_run_article"),
    )
    op.create_index("ix_listing_snapshots_article_no", "listing_snapshots", ["article_no"], unique=False)
    op.create_index("ix_listing_snapshots_complex_no", "listing_snapshots", ["complex_no"], unique=False)
    op.create_index("ix_listing_snapshots_crawl_run_id", "listing_snapshots", ["crawl_run_id"], unique=False)
    op.create_index("ix_listing_snapshots_deal_price_manwon", "listing_snapshots", ["deal_price_manwon"], unique=False)
    op.create_index("ix_listing_snapshots_observed_at", "listing_snapshots", ["observed_at"], unique=False)
    op.create_index("ix_listing_snapshots_trade_type_name", "listing_snapshots", ["trade_type_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_listing_snapshots_trade_type_name", table_name="listing_snapshots")
    op.drop_index("ix_listing_snapshots_observed_at", table_name="listing_snapshots")
    op.drop_index("ix_listing_snapshots_deal_price_manwon", table_name="listing_snapshots")
    op.drop_index("ix_listing_snapshots_crawl_run_id", table_name="listing_snapshots")
    op.drop_index("ix_listing_snapshots_complex_no", table_name="listing_snapshots")
    op.drop_index("ix_listing_snapshots_article_no", table_name="listing_snapshots")
    op.drop_table("listing_snapshots")

    op.drop_index("ix_alert_dispatch_logs_alert_type", table_name="alert_dispatch_logs")
    op.drop_table("alert_dispatch_logs")

    op.drop_table("user_notification_settings")

    op.drop_index("ix_auth_refresh_tokens_jti", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")

    op.drop_index("ix_user_watch_complexes_complex_no", table_name="user_watch_complexes")
    op.drop_table("user_watch_complexes")

    op.drop_table("user_presets")

    op.drop_index("ix_crawl_runs_complex_no", table_name="crawl_runs")
    op.drop_table("crawl_runs")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
