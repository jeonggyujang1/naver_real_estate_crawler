import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    watch_complexes: Mapped[list["UserWatchComplex"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    presets: Mapped[list["UserPreset"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["AuthRefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    access_token_revocations: Mapped[list["AuthAccessTokenRevocation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notification_setting: Mapped["UserNotificationSetting | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    alert_dispatch_logs: Mapped[list["AlertDispatchLog"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserWatchComplex(Base):
    __tablename__ = "user_watch_complexes"
    __table_args__ = (UniqueConstraint("user_id", "complex_no", name="uq_user_complex"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    complex_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    complex_name: Mapped[str | None] = mapped_column(String(255))
    sido_name: Mapped[str | None] = mapped_column(String(100))
    gugun_name: Mapped[str | None] = mapped_column(String(100))
    dong_name: Mapped[str | None] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="watch_complexes")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    complex_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SUCCESS")
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    listings: Mapped[list["ListingSnapshot"]] = relationship(back_populates="crawl_run", cascade="all, delete-orphan")


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"
    __table_args__ = (UniqueConstraint("crawl_run_id", "article_no", name="uq_run_article"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crawl_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    complex_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    article_no: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    article_name: Mapped[str | None] = mapped_column(String(255))
    trade_type_name: Mapped[str | None] = mapped_column(String(30), index=True)
    deal_price_text: Mapped[str | None] = mapped_column(String(50))
    rent_price_text: Mapped[str | None] = mapped_column(String(50))
    deal_price_manwon: Mapped[int | None] = mapped_column(Integer, index=True)
    rent_price_manwon: Mapped[int | None] = mapped_column(Integer)
    area_m2: Mapped[float | None] = mapped_column(Float)
    floor_info: Mapped[str | None] = mapped_column(String(50))
    direction: Mapped[str | None] = mapped_column(String(30))
    confirmed_date: Mapped[date | None] = mapped_column(Date)
    listing_meta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    crawl_run: Mapped["CrawlRun"] = relationship(back_populates="listings")


class UserPreset(Base):
    __tablename__ = "user_presets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_preset_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False, default="complex")
    filter_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    chart_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="presets")


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("jti", name="uq_refresh_jti"),
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class AuthAccessTokenRevocation(Base):
    __tablename__ = "auth_access_token_revocations"
    __table_args__ = (UniqueConstraint("jti", name="uq_access_jti"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="access_token_revocations")


class UserNotificationSetting(Base):
    __tablename__ = "user_notification_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_address: Mapped[str | None] = mapped_column(String(255))
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100))
    bargain_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bargain_lookback_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    bargain_discount_threshold: Mapped[float] = mapped_column(Float, default=0.08, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="notification_setting")


class AlertDispatchLog(Base):
    __tablename__ = "alert_dispatch_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", "alert_type", "dedupe_key", name="uq_alert_dispatch_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="alert_dispatch_logs")
