from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

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
    AuthRefreshToken,
    CrawlRun,
    ListingSnapshot,
    User,
    UserNotificationSetting,
    UserPreset,
    UserWatchComplex,
)
from app.services.alerts import collect_user_bargains, dispatch_user_bargain_alerts
from app.services.analytics import detect_bargains, fetch_compare_trend, fetch_complex_trend
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
    db: Session = Depends(get_db),
) -> dict[str, object]:
    rows = fetch_complex_trend(
        db=db,
        complex_no=complex_no,
        days=days,
        trade_type_name=trade_type_name,
    )
    return {
        "complex_no": complex_no,
        "days": days,
        "trade_type_name": trade_type_name,
        "series": rows,
    }


@app.get("/analytics/compare")
def analytics_compare(
    complex_nos: list[int] = Query(..., min_length=2),
    days: int = 30,
    trade_type_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        enforce_compare_limit(db=db, user_id=current_user.id, requested_complex_count=len(complex_nos))
    except BillingError as exc:
        raise _map_billing_error(exc) from exc

    return {
        "complex_nos": complex_nos,
        "days": days,
        "trade_type_name": trade_type_name,
        "series": fetch_compare_trend(
            db=db,
            complex_nos=complex_nos,
            days=days,
            trade_type_name=trade_type_name,
        ),
    }


@app.get("/analytics/bargains/{complex_no}")
def analytics_bargains(
    complex_no: int,
    lookback_days: int = 30,
    discount_threshold: float = 0.08,
    trade_type_name: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    items = detect_bargains(
        db=db,
        complex_no=complex_no,
        lookback_days=lookback_days,
        discount_threshold=discount_threshold,
        trade_type_name=trade_type_name,
    )
    return {
        "complex_no": complex_no,
        "lookback_days": lookback_days,
        "discount_threshold": discount_threshold,
        "trade_type_name": trade_type_name,
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
) -> dict[str, str]:
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

    user = User(email=normalized_email, password_hash=hash_password(password))
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
    db.commit()
    db.refresh(user)

    return {"user_id": str(user.id), "email": user.email}


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

    new_hash = maybe_rehash_password(password, user.password_hash)
    if new_hash:
        user.password_hash = new_hash

    payload, _refresh_jti = _issue_auth_tokens(db=db, user_id=user.id)
    db.commit()
    return payload


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
    watches = db.scalars(
        select(UserWatchComplex)
        .where(UserWatchComplex.user_id == current_user.id)
        .order_by(UserWatchComplex.created_at.desc())
    ).all()
    complex_nos = list({item.complex_no for item in watches})
    scheduler_complex_nos = set(_parse_csv_ints(settings.scheduler_complex_nos_csv))
    scheduler_times = sorted([token.strip() for token in settings.scheduler_times_csv.split(",") if token.strip()])

    if not complex_nos:
        return {
            "count": 0,
            "auto_collect": {
                "enabled": settings.scheduler_enabled,
                "timezone": settings.scheduler_timezone,
                "times": scheduler_times,
                "poll_seconds": settings.scheduler_poll_seconds,
                "configured_complex_count": len(scheduler_complex_nos),
                "note": "자동수집 주기는 서버 전역 설정입니다. 계정별로 개별 주기를 다르게 두지는 않습니다.",
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
                "auto_collect_target": watch.complex_no in scheduler_complex_nos,
            }
        )

    return {
        "count": len(items),
        "auto_collect": {
            "enabled": settings.scheduler_enabled,
            "timezone": settings.scheduler_timezone,
            "times": scheduler_times,
            "poll_seconds": settings.scheduler_poll_seconds,
            "configured_complex_count": len(scheduler_complex_nos),
            "note": "자동수집 주기는 서버 전역 설정입니다. 계정별로 개별 주기를 다르게 두지는 않습니다.",
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = db.get(UserNotificationSetting, current_user.id)
    resolved_lookback_days = lookback_days or (setting.bargain_lookback_days if setting else 30)
    resolved_discount_threshold = discount_threshold or (setting.bargain_discount_threshold if setting else 0.08)
    alerts = collect_user_bargains(
        db=db,
        user_id=current_user.id,
        lookback_days=resolved_lookback_days,
        discount_threshold=resolved_discount_threshold,
        trade_type_name=trade_type_name,
    )
    return {
        "count": len(alerts),
        "items": alerts,
        "lookback_days": resolved_lookback_days,
        "discount_threshold": resolved_discount_threshold,
        "trade_type_name": trade_type_name,
    }


@app.get("/me/notification-settings")
def me_notification_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = db.get(UserNotificationSetting, current_user.id)
    if setting is None:
        setting = UserNotificationSetting(
            user_id=current_user.id,
            email_enabled=True,
            email_address=current_user.email,
        )
        db.add(setting)
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    setting = db.get(UserNotificationSetting, current_user.id)
    if setting is None:
        setting = UserNotificationSetting(
            user_id=current_user.id,
            email_enabled=True,
            email_address=current_user.email,
        )
        db.add(setting)

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

    items = collect_user_bargains(
        db=db,
        user_id=current_user.id,
        lookback_days=setting.bargain_lookback_days,
        discount_threshold=setting.bargain_discount_threshold,
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
        **dispatch_result,
    }
