import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BillingCheckoutSession, UserPreset, UserSubscription, UserWatchComplex


@dataclass(slots=True, frozen=True)
class BillingPlan:
    code: str
    display_name: str
    monthly_price_krw: int
    watch_complex_limit: int | None
    preset_limit: int | None
    compare_complex_limit: int | None
    manual_alert_dispatch: bool


class BillingError(Exception):
    def __init__(self, detail: str, status_code: int = 403) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


FREE_PLAN = BillingPlan(
    code="FREE",
    display_name="Free",
    monthly_price_krw=0,
    watch_complex_limit=3,
    preset_limit=3,
    compare_complex_limit=2,
    manual_alert_dispatch=False,
)

PRO_PLAN = BillingPlan(
    code="PRO",
    display_name="Pro",
    monthly_price_krw=9900,
    watch_complex_limit=None,
    preset_limit=None,
    compare_complex_limit=None,
    manual_alert_dispatch=True,
)

PLAN_CATALOG: dict[str, BillingPlan] = {
    FREE_PLAN.code: FREE_PLAN,
    PRO_PLAN.code: PRO_PLAN,
}
PAID_PLAN_CODES = {PRO_PLAN.code}


def _normalize_plan_code(plan_code: str | None) -> str:
    candidate = (plan_code or FREE_PLAN.code).strip().upper()
    if candidate in PLAN_CATALOG:
        return candidate
    return FREE_PLAN.code


def ensure_user_subscription(db: Session, user_id: UUID) -> UserSubscription:
    subscription = db.get(UserSubscription, user_id)
    if subscription is not None:
        return subscription

    subscription = UserSubscription(
        user_id=user_id,
        plan_code=FREE_PLAN.code,
        status="ACTIVE",
        provider="dummy",
    )
    db.add(subscription)
    db.flush()
    return subscription


def get_user_entitlements(db: Session, user_id: UUID) -> dict[str, object]:
    subscription = ensure_user_subscription(db=db, user_id=user_id)
    active_plan_code = _normalize_plan_code(subscription.plan_code if subscription.status == "ACTIVE" else FREE_PLAN.code)
    plan = PLAN_CATALOG[active_plan_code]
    return {
        "plan_code": plan.code,
        "status": subscription.status,
        "provider": subscription.provider,
        "monthly_price_krw": plan.monthly_price_krw,
        "limits": {
            "watch_complex_limit": plan.watch_complex_limit,
            "preset_limit": plan.preset_limit,
            "compare_complex_limit": plan.compare_complex_limit,
            "manual_alert_dispatch": plan.manual_alert_dispatch,
        },
    }


def _count_rows_by_user(db: Session, model: type[UserWatchComplex] | type[UserPreset], user_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.user_id == user_id)
        )
        or 0
    )


def enforce_watch_complex_limit(db: Session, user_id: UUID) -> None:
    entitlements = get_user_entitlements(db=db, user_id=user_id)
    limit = entitlements["limits"]["watch_complex_limit"]
    if isinstance(limit, int):
        current_count = _count_rows_by_user(db=db, model=UserWatchComplex, user_id=user_id)
        if current_count >= limit:
            raise BillingError(
                detail=f"무료 플랜에서는 관심 단지를 최대 {limit}개까지 등록할 수 있습니다.",
                status_code=403,
            )


def enforce_preset_limit(db: Session, user_id: UUID) -> None:
    entitlements = get_user_entitlements(db=db, user_id=user_id)
    limit = entitlements["limits"]["preset_limit"]
    if isinstance(limit, int):
        current_count = _count_rows_by_user(db=db, model=UserPreset, user_id=user_id)
        if current_count >= limit:
            raise BillingError(
                detail=f"무료 플랜에서는 프리셋을 최대 {limit}개까지 저장할 수 있습니다.",
                status_code=403,
            )


def enforce_compare_limit(db: Session, user_id: UUID, requested_complex_count: int) -> None:
    entitlements = get_user_entitlements(db=db, user_id=user_id)
    limit = entitlements["limits"]["compare_complex_limit"]
    if isinstance(limit, int) and requested_complex_count > limit:
        raise BillingError(
            detail=f"무료 플랜에서는 단지 비교를 최대 {limit}개까지만 지원합니다.",
            status_code=403,
        )


def enforce_manual_alert_dispatch(db: Session, user_id: UUID) -> None:
    entitlements = get_user_entitlements(db=db, user_id=user_id)
    enabled = bool(entitlements["limits"]["manual_alert_dispatch"])
    if not enabled:
        raise BillingError(
            detail="수동 급매 알림 발송은 PRO 플랜에서 사용할 수 있습니다.",
            status_code=403,
        )


def create_dummy_checkout_session(db: Session, user_id: UUID, plan_code: str) -> BillingCheckoutSession:
    normalized_plan_code = _normalize_plan_code(plan_code)
    if normalized_plan_code not in PAID_PLAN_CODES:
        raise BillingError(detail="더미 결제는 PRO 플랜만 지원합니다.", status_code=400)

    plan = PLAN_CATALOG[normalized_plan_code]
    session = BillingCheckoutSession(
        user_id=user_id,
        provider="dummy",
        plan_code=normalized_plan_code,
        status="PENDING",
        checkout_token=secrets.token_urlsafe(24),
        amount_krw=plan.monthly_price_krw,
        currency="KRW",
        checkout_payload={"flow": "dummy", "plan_code": normalized_plan_code},
    )
    db.add(session)
    db.flush()
    return session


def complete_dummy_checkout_session(
    db: Session,
    user_id: UUID,
    checkout_token: str,
) -> tuple[BillingCheckoutSession, UserSubscription, bool]:
    checkout_session = db.scalar(
        select(BillingCheckoutSession)
        .where(
            BillingCheckoutSession.user_id == user_id,
            BillingCheckoutSession.checkout_token == checkout_token,
        )
        .with_for_update()
    )
    if checkout_session is None:
        raise BillingError(detail="결제 세션을 찾을 수 없습니다.", status_code=404)

    changed = False
    if checkout_session.status != "COMPLETED":
        checkout_session.status = "COMPLETED"
        checkout_session.completed_at = datetime.now(UTC)
        changed = True

    subscription = ensure_user_subscription(db=db, user_id=user_id)
    now = datetime.now(UTC)
    if subscription.plan_code != checkout_session.plan_code or subscription.status != "ACTIVE":
        subscription.plan_code = checkout_session.plan_code
        subscription.status = "ACTIVE"
        subscription.provider = "dummy"
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=30)
        subscription.cancel_at_period_end = False
        changed = True

    return checkout_session, subscription, changed
