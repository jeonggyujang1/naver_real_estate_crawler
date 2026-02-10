from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertDispatchLog, User, UserNotificationSetting, UserWatchComplex
from app.services.analytics import detect_bargains
from app.services.notifier import build_bargain_alert_text, send_email_message, send_telegram_message
from app.settings import Settings


def collect_user_bargains(
    db: Session,
    user_id: UUID,
    lookback_days: int,
    discount_threshold: float,
    trade_type_name: str | None = None,
    only_complex_no: int | None = None,
) -> list[dict[str, Any]]:
    stmt = select(UserWatchComplex).where(UserWatchComplex.user_id == user_id, UserWatchComplex.enabled.is_(True))
    if only_complex_no is not None:
        stmt = stmt.where(UserWatchComplex.complex_no == only_complex_no)
    watches = db.scalars(stmt).all()
    if not watches:
        return []

    alerts: list[dict[str, Any]] = []
    for watch in watches:
        rows = detect_bargains(
            db=db,
            complex_no=watch.complex_no,
            lookback_days=lookback_days,
            discount_threshold=discount_threshold,
            trade_type_name=trade_type_name,
        )
        for row in rows:
            row["complex_no"] = watch.complex_no
            row["complex_name"] = watch.complex_name
            alerts.append(row)

    alerts.sort(key=lambda row: row["discount_rate"], reverse=True)
    return alerts


def _bargain_dedupe_key(item: dict[str, Any]) -> str:
    return "bargain:{complex_no}:{article_no}:{deal_price_manwon}".format(
        complex_no=item.get("complex_no"),
        article_no=item.get("article_no"),
        deal_price_manwon=item.get("deal_price_manwon"),
    )


def _filter_unsent_items(
    db: Session,
    user_id: UUID,
    channel: str,
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    dedupe_pairs = [(_bargain_dedupe_key(item), item) for item in items]
    keys = [key for key, _item in dedupe_pairs]
    if not keys:
        return [], []

    existing_keys = set(
        db.scalars(
            select(AlertDispatchLog.dedupe_key).where(
                AlertDispatchLog.user_id == user_id,
                AlertDispatchLog.channel == channel,
                AlertDispatchLog.alert_type == "bargain",
                AlertDispatchLog.dedupe_key.in_(keys),
            )
        ).all()
    )
    unsent_items = [item for key, item in dedupe_pairs if key not in existing_keys]
    unsent_keys = [key for key, _item in dedupe_pairs if key not in existing_keys]
    return unsent_items, unsent_keys


def dispatch_user_bargain_alerts(
    db: Session,
    settings: Settings,
    user: User,
    notification_setting: UserNotificationSetting,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    result = {
        "email_sent": 0,
        "telegram_sent": 0,
        "email_reason": "",
        "telegram_reason": "",
    }
    if not items or not notification_setting.bargain_alert_enabled:
        return result

    if notification_setting.email_enabled and notification_setting.email_address:
        email_items, email_keys = _filter_unsent_items(db, user.id, "email", items)
        if email_items:
            ok, reason = send_email_message(
                settings=settings,
                to_email=notification_setting.email_address,
                subject="[Naver Apt Briefing] 급매 알림",
                body=build_bargain_alert_text(email_items),
            )
            result["email_reason"] = reason
            if ok:
                db.add_all(
                    [
                        AlertDispatchLog(
                            user_id=user.id,
                            channel="email",
                            alert_type="bargain",
                            dedupe_key=key,
                            payload=item,
                        )
                        for key, item in zip(email_keys, email_items)
                    ]
                )
                result["email_sent"] = len(email_items)

    if notification_setting.telegram_enabled and notification_setting.telegram_chat_id:
        telegram_items, telegram_keys = _filter_unsent_items(db, user.id, "telegram", items)
        if telegram_items:
            ok, reason = send_telegram_message(
                settings=settings,
                chat_id=notification_setting.telegram_chat_id,
                text=build_bargain_alert_text(telegram_items),
            )
            result["telegram_reason"] = reason
            if ok:
                db.add_all(
                    [
                        AlertDispatchLog(
                            user_id=user.id,
                            channel="telegram",
                            alert_type="bargain",
                            dedupe_key=key,
                            payload=item,
                        )
                        for key, item in zip(telegram_keys, telegram_items)
                    ]
                )
                result["telegram_sent"] = len(telegram_items)

    return result
