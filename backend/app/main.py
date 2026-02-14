import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.naver_client import NaverLandClient
from app.db import get_db, init_db
from app.models import (
    AuthAccessTokenRevocation,
    AuthEmailVerificationToken,
    AuthRefreshToken,
    CrawlRun,
    ListingSnapshot,
    SchedulerConfig,
    User,
    UserNotificationSetting,
    UserPreset,
    UserWatchComplex,
)
from app.services.alerts import dispatch_user_bargain_alerts
from app.services.analytics import (
    detect_bargains,
    fetch_compare_trend,
    fetch_complex_trend,
    normalize_trade_type_name,
)
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    maybe_rehash_password,
    verify_password,
)
from app.services.billing import (
    BillingError,
    complete_dummy_checkout_session,
    create_dummy_checkout_session,
    enforce_compare_limit,
    enforce_manual_alert_dispatch,
    enforce_preset_limit,
    enforce_watch_complex_limit,
    ensure_user_subscription,
    get_user_entitlements,
)
from app.services.ingest import ingest_complex_snapshot
from app.services.notifier import send_email_message
from app.settings import get_settings

settings = get_settings()
REGISTER_ATTEMPTS: dict[str, list[datetime]] = {}

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)
web_dir = Path(__file__).parent / "web"
app.mount("/web", StaticFiles(directory=web_dir), name="web")


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header is required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required")
    return authorization.split(" ", 1)[1].strip()


def _decode_access_token_claims(token: str) -> tuple[UUID, str, int] | None:
    payload = decode_token(
        token=token,
        secret_key=settings.auth_secret_key,
        algorithms=[settings.auth_jwt_algorithm],
        issuer=settings.auth_jwt_issuer,
    )
    if payload is None or payload.get("type") != "access":
        return None
    try:
        user_id = UUID(str(payload.get("sub")))
        jti = str(payload.get("jti"))
        exp_ts = int(payload.get("exp"))
    except (TypeError, ValueError):
        return None
    if not jti:
        return None
    return user_id, jti, exp_ts


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    token = _extract_bearer_token(authorization)
    decoded = _decode_access_token_claims(token)
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id, jti, _exp_ts = decoded

    revoked = db.scalar(
        select(AuthAccessTokenRevocation.id).where(
            AuthAccessTokenRevocation.user_id == user_id,
            AuthAccessTokenRevocation.jti == jti,
            AuthAccessTokenRevocation.expires_at >= datetime.now(UTC),
        )
    )
    if revoked is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def _issue_auth_tokens(db: Session, user_id: Any) -> tuple[dict[str, str | int], str]:
    access_token, access_exp_ts = create_access_token(
        user_id=user_id,
        secret_key=settings.auth_secret_key,
        algorithm=settings.auth_jwt_algorithm,
        issuer=settings.auth_jwt_issuer,
        ttl_minutes=settings.auth_access_token_ttl_minutes,
    )
    refresh_token, refresh_jti, refresh_exp_ts = create_refresh_token(
        user_id=user_id,
        secret_key=settings.auth_secret_key,
        algorithm=settings.auth_jwt_algorithm,
        issuer=settings.auth_jwt_issuer,
        ttl_days=settings.auth_refresh_token_ttl_days,
    )
    refresh_record = AuthRefreshToken(
        user_id=user_id,
        jti=refresh_jti,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.fromtimestamp(refresh_exp_ts, tz=UTC),
    )
    db.add(refresh_record)
    return (
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "access_expires_at_unix": access_exp_ts,
            "refresh_expires_at_unix": refresh_exp_ts,
        },
        refresh_jti,
    )


def _map_crawler_runtime_error(exc: RuntimeError) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    if (
        "429" in message
        or "too many requests" in lowered
        or "rate limit" in lowered
        or "too_many_requests" in lowered
    ):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="네이버 부동산 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"네이버 부동산 응답 오류: {message}",
    )


def _map_billing_error(exc: BillingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _parse_csv_ints(raw: str) -> list[int]:
    result: list[int] = []
    for token in raw.split(","):
        value = token.strip()
        if value.isdigit():
            result.append(int(value))
    return result


def _resolve_client_key(request: Request, x_forwarded_for: str | None) -> str:
    if x_forwarded_for:
        first = x_forwarded_for.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_registration_rate_limit(client_key: str) -> None:
    limit = settings.auth_register_rate_limit_per_window
    window = timedelta(minutes=settings.auth_register_rate_limit_window_minutes)
    now = datetime.now(UTC)
    attempts = REGISTER_ATTEMPTS.setdefault(client_key, [])
    cutoff = now - window
    attempts[:] = [ts for ts in attempts if ts >= cutoff]
    if len(attempts) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="회원가입 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
        )
    attempts.append(now)


def _resolve_optional_current_user(authorization: str | None, db: Session) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    decoded = _decode_access_token_claims(token)
    if decoded is None:
        return None
    user_id, jti, _exp_ts = decoded
    revoked = db.scalar(
        select(AuthAccessTokenRevocation.id).where(
            AuthAccessTokenRevocation.user_id == user_id,
            AuthAccessTokenRevocation.jti == jti,
            AuthAccessTokenRevocation.expires_at >= datetime.now(UTC),
        )
    )
    if revoked is not None:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def _get_or_create_notification_setting(db: Session, user: User) -> UserNotificationSetting:
    setting = db.get(UserNotificationSetting, user.id)
    if setting is None:
        setting = UserNotificationSetting(
            user_id=user.id,
            email_enabled=True,
            email_address=user.email,
        )
        db.add(setting)
        db.flush()
    return setting


def _normalize_interest_trade_type(raw: str | None) -> str:
    normalized = (raw or "").strip()
    if not normalized or normalized.upper() == "ALL":
        return "ALL"
    if normalized not in {"매매", "전세", "월세"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid interest_trade_type")
    return normalized


def _resolve_trade_type_and_conversion(
    *,
    db: Session,
    requested_trade_type_name: str | None,
    requested_monthly_conversion_rate_pct: float | None,
    user: User | None,
) -> tuple[str, float]:
    resolved_trade_type_name = normalize_trade_type_name(requested_trade_type_name)
    resolved_monthly_conversion_rate_pct = settings.jeonse_monthly_conversion_rate_default

    setting: UserNotificationSetting | None = None
    if user is not None:
        setting = db.get(UserNotificationSetting, user.id)

    if resolved_trade_type_name is None and setting is not None:
        preferred = _normalize_interest_trade_type(setting.interest_trade_type)
        if preferred != "ALL":
            resolved_trade_type_name = preferred

    if requested_monthly_conversion_rate_pct is not None:
        resolved_monthly_conversion_rate_pct = float(requested_monthly_conversion_rate_pct)
    elif setting is not None and setting.monthly_rent_conversion_rate_pct is not None:
        resolved_monthly_conversion_rate_pct = float(setting.monthly_rent_conversion_rate_pct)

    if resolved_trade_type_name is None:
        # Preserve prior behavior unless user preference explicitly selects another trade type.
        resolved_trade_type_name = "매매"

    if (
        resolved_monthly_conversion_rate_pct < 0.1
        or resolved_monthly_conversion_rate_pct > 30.0
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid monthly_conversion_rate_pct")

    return resolved_trade_type_name, resolved_monthly_conversion_rate_pct


def _collect_user_bargains_with_preferences(
    *,
    db: Session,
    user: User,
    lookback_days: int,
    discount_threshold: float,
    requested_trade_type_name: str | None,
    requested_monthly_conversion_rate_pct: float | None,
    only_complex_no: int | None = None,
) -> tuple[list[dict[str, Any]], str, float]:
    resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=requested_trade_type_name,
        requested_monthly_conversion_rate_pct=requested_monthly_conversion_rate_pct,
        user=user,
    )

    stmt = select(UserWatchComplex).where(
        UserWatchComplex.user_id == user.id,
        UserWatchComplex.enabled.is_(True),
    )
    if only_complex_no is not None:
        stmt = stmt.where(UserWatchComplex.complex_no == only_complex_no)
    watches = db.scalars(stmt).all()

    alerts: list[dict[str, Any]] = []
    for watch in watches:
        rows = detect_bargains(
            db=db,
            complex_no=watch.complex_no,
            lookback_days=lookback_days,
            discount_threshold=discount_threshold,
            trade_type_name=resolved_trade_type_name,
            monthly_conversion_rate_pct=resolved_monthly_conversion_rate_pct,
        )
        for row in rows:
            row["complex_no"] = watch.complex_no
            row["complex_name"] = watch.complex_name
            alerts.append(row)

    alerts.sort(key=lambda row: float(row.get("discount_rate") or 0.0), reverse=True)
    return alerts, resolved_trade_type_name, resolved_monthly_conversion_rate_pct


def _parse_scheduler_times(raw: str) -> list[str]:
    result: list[str] = []
    for token in raw.split(","):
        value = token.strip()
        if len(value) == 5 and value[2] == ":" and value[:2].isdigit() and value[3:].isdigit():
            hour = int(value[:2])
            minute = int(value[3:])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                result.append(f"{hour:02d}:{minute:02d}")
    return sorted(set(result))


def _serialize_scheduler_config(config: SchedulerConfig, configured_complex_count: int) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "timezone": config.timezone,
        "times": _parse_scheduler_times(config.times_csv),
        "times_csv": config.times_csv,
        "poll_seconds": config.poll_seconds,
        "reuse_bucket_hours": config.reuse_bucket_hours,
        "configured_complex_count": configured_complex_count,
        "updated_by_user_id": str(config.updated_by_user_id) if config.updated_by_user_id else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _get_or_create_scheduler_config(db: Session) -> SchedulerConfig:
    config = db.get(SchedulerConfig, 1)
    if config is not None:
        return config

    config = SchedulerConfig(
        id=1,
        enabled=settings.scheduler_enabled,
        timezone=settings.scheduler_timezone,
        times_csv=settings.scheduler_times_csv,
        poll_seconds=settings.scheduler_poll_seconds,
        reuse_bucket_hours=settings.crawler_reuse_window_hours,
    )
    db.add(config)
    db.flush()
    return config


def _build_email_verification_link(token: str) -> str:
    base = settings.auth_email_verification_base_url.rstrip("/")
    return f"{base}/auth/verify-email?token={token}"


def _issue_email_verification_token(db: Session, user_id: UUID) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.auth_email_verification_ttl_minutes)
    db.add(
        AuthEmailVerificationToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    return raw_token, expires_at


@app.on_event("startup")
async def startup_event() -> None:
    if settings.auto_create_tables and settings.app_env == "dev":
        init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (web_dir / "index.html").read_text(encoding="utf-8")


@app.get("/meta")
def meta() -> dict[str, str | int]:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "crawler_interval_minutes": settings.crawler_interval_minutes,
        "crawler_max_retry": settings.crawler_max_retry,
        "crawler_reuse_window_hours": settings.crawler_reuse_window_hours,
    }


@app.get("/scheduler/config")
def scheduler_config_get(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    del current_user  # currently any authenticated user can update scheduler config.
    config = _get_or_create_scheduler_config(db=db)
    configured_complex_count = int(
        db.scalar(
            select(func.count(func.distinct(UserWatchComplex.complex_no))).where(UserWatchComplex.enabled.is_(True))
        )
        or 0
    )
    db.commit()
    return _serialize_scheduler_config(config=config, configured_complex_count=configured_complex_count)


@app.put("/scheduler/config")
def scheduler_config_update(
    enabled: bool = Body(..., embed=True),
    timezone: str = Body(..., embed=True),
    times_csv: str = Body(..., embed=True),
    poll_seconds: int = Body(..., embed=True),
    reuse_bucket_hours: int = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized_timezone = timezone.strip()
    try:
        ZoneInfo(normalized_timezone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timezone") from exc

    normalized_times = _parse_scheduler_times(times_csv)
    if not normalized_times:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="times_csv must contain at least one valid HH:MM value",
        )

    if poll_seconds < 5 or poll_seconds > 300:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="poll_seconds must be between 5 and 300")
    if reuse_bucket_hours < 0 or reuse_bucket_hours > 24:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reuse_bucket_hours must be between 0 and 24",
        )
    if reuse_bucket_hours not in {0, 6, 12, 24}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reuse_bucket_hours must be one of: 0, 6, 12, 24",
        )

    config = _get_or_create_scheduler_config(db=db)
    config.enabled = enabled
    config.timezone = normalized_timezone
    config.times_csv = ",".join(normalized_times)
    config.poll_seconds = poll_seconds
    config.reuse_bucket_hours = reuse_bucket_hours
    config.updated_by_user_id = current_user.id
    db.commit()
    db.refresh(config)

    configured_complex_count = int(
        db.scalar(
            select(func.count(func.distinct(UserWatchComplex.complex_no))).where(UserWatchComplex.enabled.is_(True))
        )
        or 0
    )
    return _serialize_scheduler_config(config=config, configured_complex_count=configured_complex_count)


@app.get("/crawler/articles/{complex_no}")
def crawler_articles(complex_no: int, page: int = 1) -> dict[str, object]:
    client = NaverLandClient(settings=settings)
    try:
        payload = client.fetch_complex_articles(complex_no=complex_no, page=page)
    except RuntimeError as exc:
        raise _map_crawler_runtime_error(exc) from exc
    items = client.summarize_articles(payload)
    return {
        "complex_no": complex_no,
        "page": page,
        "count": len(items),
        "items": items,
    }


@app.get("/crawler/search/complexes")
def crawler_search_complexes(
    keyword: str = Query(..., min_length=2),
    limit: int = 10,
) -> dict[str, object]:
    normalized_keyword = keyword.strip()
    if len(normalized_keyword) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="keyword must be at least 2 characters")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 20")

    client = NaverLandClient(settings=settings)
    try:
        items = client.search_complexes(keyword=normalized_keyword, limit=limit)
    except RuntimeError as exc:
        raise _map_crawler_runtime_error(exc) from exc

    return {
        "keyword": normalized_keyword,
        "count": len(items),
        "items": items,
    }


@app.post("/crawler/ingest/{complex_no}")
def crawler_ingest(
    complex_no: int,
    page: int = 1,
    max_pages: int = 1,
    force: bool = False,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page must be >= 1")
    if max_pages < 1 or max_pages > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_pages must be between 1 and 20")

    try:
        return ingest_complex_snapshot(
            db=db,
            settings=settings,
            complex_no=complex_no,
            page=page,
            max_pages=max_pages,
            reuse_window_hours=0 if force else settings.crawler_reuse_window_hours,
        )
    except RuntimeError as exc:
        raise _map_crawler_runtime_error(exc) from exc


@app.get("/analytics/trend/{complex_no}")
def analytics_trend(
    complex_no: int,
    days: int = 30,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float | None = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    optional_user = _resolve_optional_current_user(authorization=authorization, db=db)
    resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=trade_type_name,
        requested_monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        user=optional_user,
    )
    rows = fetch_complex_trend(
        db=db,
        complex_no=complex_no,
        days=days,
        trade_type_name=resolved_trade_type_name,
        monthly_conversion_rate_pct=resolved_monthly_conversion_rate_pct,
    )
    return {
        "complex_no": complex_no,
        "days": days,
        "trade_type_name": resolved_trade_type_name,
        "monthly_conversion_rate_pct": resolved_monthly_conversion_rate_pct,
        "series": rows,
    }


@app.get("/analytics/compare")
def analytics_compare(
    complex_nos: list[int] = Query(..., min_length=2),
    days: int = 30,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        enforce_compare_limit(db=db, user_id=current_user.id, requested_complex_count=len(complex_nos))
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=trade_type_name,
        requested_monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        user=current_user,
    )

    return {
        "complex_nos": complex_nos,
        "days": days,
        "trade_type_name": resolved_trade_type_name,
        "monthly_conversion_rate_pct": resolved_monthly_conversion_rate_pct,
        "series": fetch_compare_trend(
            db=db,
            complex_nos=complex_nos,
            days=days,
            trade_type_name=resolved_trade_type_name,
            monthly_conversion_rate_pct=resolved_monthly_conversion_rate_pct,
        ),
    }


@app.get("/analytics/bargains/{complex_no}")
def analytics_bargains(
    complex_no: int,
    lookback_days: int = 30,
    discount_threshold: float = 0.08,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float | None = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    optional_user = _resolve_optional_current_user(authorization=authorization, db=db)
    resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=trade_type_name,
        requested_monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        user=optional_user,
    )
    items = detect_bargains(
        db=db,
        complex_no=complex_no,
        lookback_days=lookback_days,
        discount_threshold=discount_threshold,
        trade_type_name=resolved_trade_type_name,
        monthly_conversion_rate_pct=resolved_monthly_conversion_rate_pct,
    )
    return {
        "complex_no": complex_no,
        "lookback_days": lookback_days,
        "discount_threshold": discount_threshold,
        "trade_type_name": resolved_trade_type_name,
        "monthly_conversion_rate_pct": resolved_monthly_conversion_rate_pct,
        "count": len(items),
        "items": items,
    }


@app.post("/auth/register")
def auth_register(
    request: Request,
    email: str = Body(..., embed=True),
    password: str = Body(..., embed=True, min_length=8),
    invite_code: str | None = Body(None, embed=True),
    x_forwarded_for: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client_key = _resolve_client_key(request=request, x_forwarded_for=x_forwarded_for)
    _enforce_registration_rate_limit(client_key=client_key)

    expected_invite_code = (settings.auth_register_invite_code or "").strip()
    if expected_invite_code:
        if (invite_code or "").strip() != expected_invite_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="가입 승인 코드가 올바르지 않습니다.",
            )

    normalized_email = email.strip().lower()
    existing_user = db.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    verification_required = settings.auth_email_verification_required
    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        email_verified=not verification_required,
    )
    db.add(user)
    db.flush()
    db.add(
        UserNotificationSetting(
            user_id=user.id,
            email_enabled=True,
            email_address=user.email,
        )
    )
    ensure_user_subscription(db=db, user_id=user.id)

    verification_sent = False
    verification_message = "verification not required"
    verification_link: str | None = None
    verification_expires_at: datetime | None = None
    if verification_required:
        raw_token, verification_expires_at = _issue_email_verification_token(db=db, user_id=user.id)
        verification_link = _build_email_verification_link(token=raw_token)
        email_subject = "[Naver Apt Briefing] 이메일 인증을 완료해주세요"
        email_body = (
            "회원가입을 완료하려면 아래 링크를 클릭해 이메일 인증을 완료해주세요.\n\n"
            f"{verification_link}\n\n"
            f"링크 만료 시각(UTC): {verification_expires_at.isoformat()}"
        )
        verification_sent, verification_message = send_email_message(
            settings=settings,
            to_email=user.email,
            subject=email_subject,
            body=email_body,
        )

    db.commit()
    db.refresh(user)

    response: dict[str, Any] = {
        "user_id": str(user.id),
        "email": user.email,
        "email_verification_required": verification_required,
        "email_verification_sent": verification_sent,
        "email_verification_message": verification_message,
    }
    if verification_expires_at is not None:
        response["email_verification_expires_at"] = verification_expires_at.isoformat()
    if verification_required and settings.app_env != "prod":
        response["dev_email_verification_link"] = verification_link
    return response


@app.post("/auth/login")
def auth_login(
    email: str = Body(..., embed=True),
    password: str = Body(..., embed=True),
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required")

    new_hash = maybe_rehash_password(password, user.password_hash)
    if new_hash:
        user.password_hash = new_hash

    payload, _refresh_jti = _issue_auth_tokens(db=db, user_id=user.id)
    db.commit()
    return payload


@app.get("/auth/verify-email", response_class=HTMLResponse)
def auth_verify_email(
    token: str = Query(..., min_length=20),
    db: Session = Depends(get_db),
) -> str:
    token_hash = hash_token(token)
    record = db.scalar(
        select(AuthEmailVerificationToken)
        .where(AuthEmailVerificationToken.token_hash == token_hash)
        .with_for_update()
    )
    if record is None:
        return "<h3>이메일 인증 실패</h3><p>유효하지 않은 인증 링크입니다.</p>"
    if record.consumed_at is not None:
        return "<h3>이메일 인증 완료</h3><p>이미 인증이 완료된 링크입니다. 로그인해 주세요.</p>"
    if record.expires_at < datetime.now(UTC):
        return "<h3>이메일 인증 실패</h3><p>인증 링크가 만료되었습니다. 다시 요청해 주세요.</p>"

    user = db.get(User, record.user_id)
    if user is None:
        return "<h3>이메일 인증 실패</h3><p>사용자를 찾을 수 없습니다.</p>"

    user.email_verified = True
    record.consumed_at = datetime.now(UTC)
    db.commit()
    return (
        "<h3>이메일 인증 완료</h3>"
        "<p>인증이 완료되었습니다. 앱으로 돌아가 로그인해 주세요.</p>"
        "<p><a href='/'>대시보드로 이동</a></p>"
    )


@app.post("/auth/refresh")
def auth_refresh(
    refresh_token: str = Body(..., embed=True),
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    parsed = decode_refresh_token(
        token=refresh_token,
        secret_key=settings.auth_secret_key,
        algorithm=settings.auth_jwt_algorithm,
        issuer=settings.auth_jwt_issuer,
    )
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user_id, jti, _exp_ts = parsed

    token_row = db.scalar(
        select(AuthRefreshToken)
        .where(
            AuthRefreshToken.user_id == user_id,
            AuthRefreshToken.jti == jti,
        )
        .with_for_update()
    )
    if token_row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found")
    if token_row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
    if token_row.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    if token_row.token_hash != hash_token(refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    payload, new_refresh_jti = _issue_auth_tokens(db=db, user_id=user.id)
    token_row.revoked_at = datetime.now(UTC)
    token_row.replaced_by_jti = new_refresh_jti
    db.commit()
    return payload


@app.post("/auth/logout")
def auth_logout(
    refresh_token: str = Body(..., embed=True),
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    changed = False

    if authorization and authorization.startswith("Bearer "):
        access_token = authorization.split(" ", 1)[1].strip()
        decoded = _decode_access_token_claims(access_token)
        if decoded is not None:
            user_id, jti, exp_ts = decoded
            already_revoked = db.scalar(
                select(AuthAccessTokenRevocation.id).where(AuthAccessTokenRevocation.jti == jti)
            )
            if already_revoked is None:
                db.add(
                    AuthAccessTokenRevocation(
                        user_id=user_id,
                        jti=jti,
                        expires_at=datetime.fromtimestamp(exp_ts, tz=UTC),
                        revoked_at=datetime.now(UTC),
                    )
                )
                changed = True

    parsed = decode_refresh_token(
        token=refresh_token,
        secret_key=settings.auth_secret_key,
        algorithm=settings.auth_jwt_algorithm,
        issuer=settings.auth_jwt_issuer,
    )
    if parsed is not None:
        user_id, jti, _exp_ts = parsed
        token_row = db.scalar(
            select(AuthRefreshToken).where(
                AuthRefreshToken.user_id == user_id,
                AuthRefreshToken.jti == jti,
            )
        )
        if token_row is not None and token_row.revoked_at is None and token_row.token_hash == hash_token(refresh_token):
            token_row.revoked_at = datetime.now(UTC)
            changed = True

    if changed:
        db.commit()
    return {"ok": True}


@app.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"user_id": str(current_user.id), "email": current_user.email}


@app.get("/billing/me")
def billing_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return get_user_entitlements(db=db, user_id=current_user.id)


@app.post("/billing/checkout-sessions")
def billing_create_checkout_session(
    plan_code: str = Body("PRO", embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        checkout_session = create_dummy_checkout_session(
            db=db,
            user_id=current_user.id,
            plan_code=plan_code,
        )
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    db.commit()
    return {
        "checkout_session_id": str(checkout_session.id),
        "checkout_token": checkout_session.checkout_token,
        "provider": checkout_session.provider,
        "status": checkout_session.status,
        "plan_code": checkout_session.plan_code,
        "amount_krw": checkout_session.amount_krw,
        "currency": checkout_session.currency,
        "checkout_url": f"/billing/checkout-sessions/{checkout_session.checkout_token}/complete",
    }


@app.post("/billing/checkout-sessions/{checkout_token}/complete")
def billing_complete_checkout_session(
    checkout_token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        checkout_session, _subscription, changed = complete_dummy_checkout_session(
            db=db,
            user_id=current_user.id,
            checkout_token=checkout_token,
        )
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    db.commit()
    entitlements = get_user_entitlements(db=db, user_id=current_user.id)
    return {
        "ok": True,
        "changed": changed,
        "checkout_session_id": str(checkout_session.id),
        "checkout_token": checkout_session.checkout_token,
        "activated_plan_code": entitlements["plan_code"],
        "entitlements": entitlements,
    }


@app.get("/me/watch-complexes")
def me_watch_complexes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    rows = db.scalars(
        select(UserWatchComplex)
        .where(UserWatchComplex.user_id == current_user.id)
        .order_by(UserWatchComplex.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "complex_no": item.complex_no,
                "complex_name": item.complex_name,
                "sido_name": item.sido_name,
                "gugun_name": item.gugun_name,
                "dong_name": item.dong_name,
                "enabled": item.enabled,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in rows
        ]
    }


@app.get("/me/watch-complexes/collection-status")
def me_watch_complexes_collection_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scheduler_config = _get_or_create_scheduler_config(db=db)
    active_watch_complex_nos = set(
        db.scalars(
            select(UserWatchComplex.complex_no)
            .where(UserWatchComplex.enabled.is_(True))
            .distinct()
        ).all()
    )
    scheduler_times = _parse_scheduler_times(scheduler_config.times_csv)

    watches = db.scalars(
        select(UserWatchComplex)
        .where(UserWatchComplex.user_id == current_user.id)
        .order_by(UserWatchComplex.created_at.desc())
    ).all()
    complex_nos = list({item.complex_no for item in watches})

    if not complex_nos:
        return {
            "count": 0,
            "auto_collect": {
                "enabled": scheduler_config.enabled,
                "timezone": scheduler_config.timezone,
                "times": scheduler_times,
                "poll_seconds": scheduler_config.poll_seconds,
                "reuse_bucket_hours": scheduler_config.reuse_bucket_hours,
                "configured_complex_count": len(active_watch_complex_nos),
                "note": "자동수집 주기/재사용 버킷은 서버 전역 설정이며, 수집 대상은 전체 계정의 활성 관심단지입니다.",
            },
            "items": [],
        }

    latest_success_rows = db.execute(
        select(
            CrawlRun.complex_no,
            func.max(CrawlRun.completed_at).label("latest_collected_at"),
            func.max(CrawlRun.id).label("latest_success_run_id"),
        )
        .where(CrawlRun.complex_no.in_(complex_nos), CrawlRun.status == "SUCCESS")
        .group_by(CrawlRun.complex_no)
    ).all()
    latest_success_map = {
        int(row.complex_no): {
            "latest_collected_at": row.latest_collected_at,
            "latest_success_run_id": int(row.latest_success_run_id) if row.latest_success_run_id is not None else None,
        }
        for row in latest_success_rows
    }

    latest_attempt_rows = db.execute(
        select(
            CrawlRun.complex_no,
            func.max(CrawlRun.started_at).label("last_attempt_at"),
            func.max(CrawlRun.id).label("last_run_id"),
        )
        .where(CrawlRun.complex_no.in_(complex_nos))
        .group_by(CrawlRun.complex_no)
    ).all()
    last_run_id_by_complex = {
        int(row.complex_no): int(row.last_run_id) if row.last_run_id is not None else None
        for row in latest_attempt_rows
    }
    last_attempt_at_by_complex = {int(row.complex_no): row.last_attempt_at for row in latest_attempt_rows}

    all_run_ids = {
        run_id
        for run_id in [
            *(item.get("latest_success_run_id") for item in latest_success_map.values()),
            *last_run_id_by_complex.values(),
        ]
        if run_id is not None
    }

    run_meta_map: dict[int, dict[str, Any]] = {}
    if all_run_ids:
        run_rows = db.execute(
            select(CrawlRun.id, CrawlRun.status, CrawlRun.error_message).where(CrawlRun.id.in_(all_run_ids))
        ).all()
        run_meta_map = {
            int(row.id): {
                "status": row.status,
                "error_message": row.error_message,
            }
            for row in run_rows
        }

    latest_success_run_ids = [
        item["latest_success_run_id"]
        for item in latest_success_map.values()
        if item.get("latest_success_run_id") is not None
    ]
    listing_count_by_run_id: dict[int, int] = {}
    if latest_success_run_ids:
        listing_count_rows = db.execute(
            select(ListingSnapshot.crawl_run_id, func.count(ListingSnapshot.id))
            .where(ListingSnapshot.crawl_run_id.in_(latest_success_run_ids))
            .group_by(ListingSnapshot.crawl_run_id)
        ).all()
        listing_count_by_run_id = {
            int(run_id): int(count)
            for run_id, count in listing_count_rows
        }

    items: list[dict[str, Any]] = []
    for watch in watches:
        latest_success = latest_success_map.get(watch.complex_no, {})
        latest_success_run_id = latest_success.get("latest_success_run_id")
        last_run_id = last_run_id_by_complex.get(watch.complex_no)
        last_run_meta = run_meta_map.get(last_run_id) if last_run_id else None
        items.append(
            {
                "watch_id": watch.id,
                "complex_no": watch.complex_no,
                "complex_name": watch.complex_name,
                "enabled": watch.enabled,
                "created_at": watch.created_at.isoformat() if watch.created_at else None,
                "latest_collected_at": (
                    latest_success.get("latest_collected_at").isoformat()
                    if latest_success.get("latest_collected_at")
                    else None
                ),
                "latest_success_run_id": latest_success_run_id,
                "latest_listing_count": (
                    listing_count_by_run_id.get(latest_success_run_id) if latest_success_run_id is not None else None
                ),
                "last_attempt_at": (
                    last_attempt_at_by_complex.get(watch.complex_no).isoformat()
                    if last_attempt_at_by_complex.get(watch.complex_no)
                    else None
                ),
                "last_run_status": last_run_meta.get("status") if last_run_meta else None,
                "last_run_error": last_run_meta.get("error_message") if last_run_meta else None,
                "auto_collect_target": scheduler_config.enabled and watch.complex_no in active_watch_complex_nos,
            }
        )

    return {
        "count": len(items),
        "auto_collect": {
            "enabled": scheduler_config.enabled,
            "timezone": scheduler_config.timezone,
            "times": scheduler_times,
            "poll_seconds": scheduler_config.poll_seconds,
            "reuse_bucket_hours": scheduler_config.reuse_bucket_hours,
            "configured_complex_count": len(active_watch_complex_nos),
            "note": "자동수집 주기/재사용 버킷은 서버 전역 설정이며, 수집 대상은 전체 계정의 활성 관심단지입니다.",
        },
        "items": items,
    }


@app.get("/me/watch-complexes/live")
def me_watch_complexes_live(
    page: int = 1,
    max_per_complex: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page must be >= 1")
    if max_per_complex < 1 or max_per_complex > 30:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_per_complex must be between 1 and 30")

    watches = db.scalars(
        select(UserWatchComplex)
        .where(
            UserWatchComplex.user_id == current_user.id,
            UserWatchComplex.enabled.is_(True),
        )
        .order_by(UserWatchComplex.created_at.desc())
    ).all()
    if not watches:
        return {
            "count": 0,
            "page": page,
            "max_per_complex": max_per_complex,
            "items": [],
        }

    client = NaverLandClient(settings=settings)
    items: list[dict[str, Any]] = []
    for watch in watches:
        try:
            payload = client.fetch_complex_articles(complex_no=watch.complex_no, page=page)
            summaries = client.summarize_articles(payload)[:max_per_complex]
            items.append(
                {
                    "complex_no": watch.complex_no,
                    "complex_name": watch.complex_name,
                    "article_count": len(summaries),
                    "articles": summaries,
                }
            )
        except Exception as exc:  # pragma: no cover - external API/network branch
            items.append(
                {
                    "complex_no": watch.complex_no,
                    "complex_name": watch.complex_name,
                    "article_count": 0,
                    "articles": [],
                    "error": str(exc),
                }
            )

    return {
        "count": len(items),
        "page": page,
        "max_per_complex": max_per_complex,
        "items": items,
    }


@app.post("/me/watch-complexes")
def me_add_watch_complex(
    complex_no: int = Body(..., embed=True),
    complex_name: str | None = Body(None, embed=True),
    sido_name: str | None = Body(None, embed=True),
    gugun_name: str | None = Body(None, embed=True),
    dong_name: str | None = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        enforce_watch_complex_limit(db=db, user_id=current_user.id)
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    watch = UserWatchComplex(
        user_id=current_user.id,
        complex_no=complex_no,
        complex_name=complex_name,
        sido_name=sido_name,
        gugun_name=gugun_name,
        dong_name=dong_name,
        enabled=True,
    )
    db.add(watch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Complex already in watch list")

    db.refresh(watch)
    return {
        "id": watch.id,
        "complex_no": watch.complex_no,
        "complex_name": watch.complex_name,
        "enabled": watch.enabled,
    }


@app.post("/me/watch-complexes/ingest")
def me_ingest_watch_complexes(
    page: int = Body(1, embed=True),
    max_pages: int = Body(1, embed=True),
    force: bool = Body(False, embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page must be >= 1")
    if max_pages < 1 or max_pages > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_pages must be between 1 and 20")

    watches = db.scalars(
        select(UserWatchComplex)
        .where(
            UserWatchComplex.user_id == current_user.id,
            UserWatchComplex.enabled.is_(True),
        )
        .order_by(UserWatchComplex.created_at.desc())
    ).all()
    if not watches:
        return {
            "requested_complex_count": 0,
            "processed_complex_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "reused_count": 0,
            "total_listing_count": 0,
            "page": page,
            "max_pages": max_pages,
            "force": force,
            "results": [],
        }

    by_complex_name: dict[int, str | None] = {}
    for watch in watches:
        if watch.complex_no not in by_complex_name:
            by_complex_name[watch.complex_no] = watch.complex_name

    results: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    reused_count = 0
    total_listing_count = 0

    for complex_no in sorted(by_complex_name.keys()):
        try:
            ingest_result = ingest_complex_snapshot(
                db=db,
                settings=settings,
                complex_no=complex_no,
                page=page,
                max_pages=max_pages,
                reuse_window_hours=0 if force else settings.crawler_reuse_window_hours,
            )
            success_count += 1
            reused_count += int(ingest_result.get("reused") or 0)
            total_listing_count += int(ingest_result.get("listing_count") or 0)
            results.append(
                {
                    "complex_no": complex_no,
                    "complex_name": by_complex_name.get(complex_no),
                    "ok": True,
                    **ingest_result,
                }
            )
        except RuntimeError as exc:
            failure_count += 1
            mapped = _map_crawler_runtime_error(exc)
            results.append(
                {
                    "complex_no": complex_no,
                    "complex_name": by_complex_name.get(complex_no),
                    "ok": False,
                    "status_code": mapped.status_code,
                    "error": mapped.detail,
                }
            )

    return {
        "requested_complex_count": len(by_complex_name),
        "processed_complex_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "reused_count": reused_count,
        "total_listing_count": total_listing_count,
        "page": page,
        "max_pages": max_pages,
        "force": force,
        "results": results,
    }


@app.delete("/me/watch-complexes/{watch_id}")
def me_delete_watch_complex(
    watch_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    watch = db.scalar(
        select(UserWatchComplex).where(
            UserWatchComplex.id == watch_id,
            UserWatchComplex.user_id == current_user.id,
        )
    )
    if watch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watch complex not found")

    db.delete(watch)
    db.commit()
    return {"ok": True, "deleted_watch_id": watch_id}


@app.get("/me/presets")
def me_presets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    rows = db.scalars(
        select(UserPreset).where(UserPreset.user_id == current_user.id).order_by(UserPreset.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "target_type": item.target_type,
                "filter_payload": item.filter_payload,
                "chart_payload": item.chart_payload,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in rows
        ]
    }


@app.post("/me/presets")
def me_add_preset(
    name: str = Body(..., embed=True),
    target_type: str = Body("complex", embed=True),
    filter_payload: dict[str, Any] = Body(default_factory=dict, embed=True),
    chart_payload: dict[str, Any] = Body(default_factory=dict, embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        enforce_preset_limit(db=db, user_id=current_user.id)
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    preset = UserPreset(
        user_id=current_user.id,
        name=name.strip(),
        target_type=target_type.strip().lower(),
        filter_payload=filter_payload,
        chart_payload=chart_payload,
    )
    db.add(preset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preset name already exists")

    db.refresh(preset)
    return {
        "id": str(preset.id),
        "name": preset.name,
        "target_type": preset.target_type,
        "filter_payload": preset.filter_payload,
        "chart_payload": preset.chart_payload,
    }


@app.get("/me/alerts/bargains")
def me_bargain_alerts(
    lookback_days: int | None = None,
    discount_threshold: float | None = None,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = db.get(UserNotificationSetting, current_user.id)
    resolved_lookback_days = lookback_days or (setting.bargain_lookback_days if setting else 30)
    resolved_discount_threshold = discount_threshold or (setting.bargain_discount_threshold if setting else 0.08)
    alerts, resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _collect_user_bargains_with_preferences(
        db=db,
        user=current_user,
        lookback_days=resolved_lookback_days,
        discount_threshold=resolved_discount_threshold,
        requested_trade_type_name=trade_type_name,
        requested_monthly_conversion_rate_pct=monthly_conversion_rate_pct,
    )
    return {
        "count": len(alerts),
        "items": alerts,
        "lookback_days": resolved_lookback_days,
        "discount_threshold": resolved_discount_threshold,
        "trade_type_name": resolved_trade_type_name,
        "monthly_conversion_rate_pct": resolved_monthly_conversion_rate_pct,
    }


@app.get("/me/notification-settings")
def me_notification_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = _get_or_create_notification_setting(db=db, user=current_user)
    db.commit()
    db.refresh(setting)
    return {
        "email_enabled": setting.email_enabled,
        "email_address": setting.email_address,
        "telegram_enabled": setting.telegram_enabled,
        "telegram_chat_id": setting.telegram_chat_id,
        "bargain_alert_enabled": setting.bargain_alert_enabled,
        "bargain_lookback_days": setting.bargain_lookback_days,
        "bargain_discount_threshold": setting.bargain_discount_threshold,
        "interest_trade_type": _normalize_interest_trade_type(setting.interest_trade_type),
        "monthly_rent_conversion_rate_pct": setting.monthly_rent_conversion_rate_pct,
        "resolved_monthly_conversion_rate_pct": (
            setting.monthly_rent_conversion_rate_pct
            if setting.monthly_rent_conversion_rate_pct is not None
            else settings.jeonse_monthly_conversion_rate_default
        ),
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
    }


@app.put("/me/notification-settings")
def me_update_notification_settings(
    email_enabled: bool | None = Body(default=None, embed=True),
    email_address: str | None = Body(default=None, embed=True),
    telegram_enabled: bool | None = Body(default=None, embed=True),
    telegram_chat_id: str | None = Body(default=None, embed=True),
    bargain_alert_enabled: bool | None = Body(default=None, embed=True),
    bargain_lookback_days: int | None = Body(default=None, embed=True),
    bargain_discount_threshold: float | None = Body(default=None, embed=True),
    interest_trade_type: str | None = Body(default=None, embed=True),
    monthly_rent_conversion_rate_pct: float | None = Body(default=None, embed=True),
    monthly_rent_conversion_rate_use_default: bool | None = Body(default=None, embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = _get_or_create_notification_setting(db=db, user=current_user)

    if email_enabled is not None:
        setting.email_enabled = email_enabled
    if email_address is not None:
        setting.email_address = email_address.strip() or None
    if telegram_enabled is not None:
        setting.telegram_enabled = telegram_enabled
    if telegram_chat_id is not None:
        setting.telegram_chat_id = telegram_chat_id.strip() or None
    if bargain_alert_enabled is not None:
        setting.bargain_alert_enabled = bargain_alert_enabled
    if bargain_lookback_days is not None:
        if bargain_lookback_days < 1 or bargain_lookback_days > 180:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bargain_lookback_days")
        setting.bargain_lookback_days = bargain_lookback_days
    if bargain_discount_threshold is not None:
        if bargain_discount_threshold <= 0 or bargain_discount_threshold >= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bargain_discount_threshold")
        setting.bargain_discount_threshold = bargain_discount_threshold
    if interest_trade_type is not None:
        setting.interest_trade_type = _normalize_interest_trade_type(interest_trade_type)
    if monthly_rent_conversion_rate_use_default:
        setting.monthly_rent_conversion_rate_pct = None
    if monthly_rent_conversion_rate_pct is not None:
        if monthly_rent_conversion_rate_pct < 0.1 or monthly_rent_conversion_rate_pct > 30.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid monthly_rent_conversion_rate_pct",
            )
        setting.monthly_rent_conversion_rate_pct = monthly_rent_conversion_rate_pct

    db.commit()
    db.refresh(setting)
    return {
        "email_enabled": setting.email_enabled,
        "email_address": setting.email_address,
        "telegram_enabled": setting.telegram_enabled,
        "telegram_chat_id": setting.telegram_chat_id,
        "bargain_alert_enabled": setting.bargain_alert_enabled,
        "bargain_lookback_days": setting.bargain_lookback_days,
        "bargain_discount_threshold": setting.bargain_discount_threshold,
        "interest_trade_type": _normalize_interest_trade_type(setting.interest_trade_type),
        "monthly_rent_conversion_rate_pct": setting.monthly_rent_conversion_rate_pct,
        "resolved_monthly_conversion_rate_pct": (
            setting.monthly_rent_conversion_rate_pct
            if setting.monthly_rent_conversion_rate_pct is not None
            else settings.jeonse_monthly_conversion_rate_default
        ),
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
    }


@app.post("/me/alerts/bargains/dispatch")
def me_dispatch_bargain_alerts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        enforce_manual_alert_dispatch(db=db, user_id=current_user.id)
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    setting = db.get(UserNotificationSetting, current_user.id)
    if setting is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Notification setting not configured")

    items, resolved_trade_type_name, resolved_monthly_conversion_rate_pct = _collect_user_bargains_with_preferences(
        db=db,
        user=current_user,
        lookback_days=setting.bargain_lookback_days,
        discount_threshold=setting.bargain_discount_threshold,
        requested_trade_type_name=setting.interest_trade_type,
        requested_monthly_conversion_rate_pct=setting.monthly_rent_conversion_rate_pct,
    )
    dispatch_result = dispatch_user_bargain_alerts(
        db=db,
        settings=settings,
        user=current_user,
        notification_setting=setting,
        items=items,
    )
    if dispatch_result["email_sent"] or dispatch_result["telegram_sent"]:
        db.commit()
    return {
        "candidate_count": len(items),
        "trade_type_name": resolved_trade_type_name,
        "monthly_conversion_rate_pct": resolved_monthly_conversion_rate_pct,
        **dispatch_result,
    }
