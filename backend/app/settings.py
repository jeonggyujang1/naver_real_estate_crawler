from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Naver Apt Briefing API"
    app_env: str = Field(default="dev", pattern="^(dev|staging|prod)$")
    app_version: str = "0.1.0"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/naver_apt_briefing"
    redis_url: str = "redis://localhost:6379/0"

    crawler_interval_minutes: int = Field(default=60, ge=5, le=1440)
    crawler_max_retry: int = Field(default=3, ge=0, le=10)
    crawler_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    auto_create_tables: bool = False
    scheduler_enabled: bool = False
    scheduler_timezone: str = "Asia/Seoul"
    scheduler_poll_seconds: int = Field(default=20, ge=5, le=300)
    scheduler_times_csv: str = "09:00,18:00"
    scheduler_complex_nos_csv: str = ""
    auth_secret_key: str = "change-me-in-prod"
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str = "naver-apt-briefing"
    auth_access_token_ttl_minutes: int = Field(default=15, ge=5, le=60)
    auth_refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)

    smtp_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_sender_email: str | None = None
    smtp_use_tls: bool = True

    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_api_base_url: str = "https://api.telegram.org"

    naver_land_base_url: str = "https://new.land.naver.com"
    naver_land_authorization: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
