from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import AlertDispatchLog, CrawlRun, ListingSnapshot, User, UserNotificationSetting, UserWatchComplex
from app.services.analytics import detect_bargains, to_effective_price_manwon
from app.services.notifier import build_bargain_alert_text, send_email_message, send_telegram_message
from app.settings import Settings


def _normalize_interest_trade_type(raw: str | None) -> str:
    normalized = (raw or "").strip()
    if not normalized or normalized.upper() == "ALL":
        return "매매"
    if normalized in {"매매", "전세", "월세"}:
        return normalized
    return "매매"


def _resolve_monthly_conversion_rate(
    settings: Settings,
    notification_setting: UserNotificationSetting,
) -> float:
    if notification_setting.monthly_rent_conversion_rate_pct is not None:
        return float(notification_setting.monthly_rent_conversion_rate_pct)
    return float(settings.jeonse_monthly_conversion_rate_default)


def collect_user_bargains(
    db: Session,
    user_id: UUID,
    lookback_days: int,
    discount_threshold: float,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float = 5.1,
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
            monthly_conversion_rate_pct=monthly_conversion_rate_pct,
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


def collect_user_daily_briefing(
    db: Session,
    settings: Settings,
    user_id: UUID,
    notification_setting: UserNotificationSetting,
) -> dict[str, Any]:
    trade_type_name = _normalize_interest_trade_type(notification_setting.interest_trade_type)
    conversion_rate = _resolve_monthly_conversion_rate(settings=settings, notification_setting=notification_setting)

    watches = db.scalars(
        select(UserWatchComplex)
        .where(UserWatchComplex.user_id == user_id, UserWatchComplex.enabled.is_(True))
        .order_by(UserWatchComplex.created_at.asc())
    ).all()
    if not watches:
        return {
            "trade_type_name": trade_type_name,
            "monthly_conversion_rate_pct": conversion_rate,
            "complex_summaries": [],
            "overall": None,
            "bargains": [],
        }

    complex_summaries: list[dict[str, Any]] = []
    overall_rows: list[dict[str, Any]] = []
    for watch in watches:
        latest_run_id = db.scalar(
            select(CrawlRun.id)
            .where(CrawlRun.complex_no == watch.complex_no, CrawlRun.status == "SUCCESS")
            .order_by(desc(CrawlRun.started_at))
            .limit(1)
        )
        if latest_run_id is None:
            continue

        listing_stmt = select(ListingSnapshot).where(ListingSnapshot.crawl_run_id == latest_run_id)
        if trade_type_name:
            listing_stmt = listing_stmt.where(ListingSnapshot.trade_type_name == trade_type_name)
        listings = db.scalars(listing_stmt).all()

        priced_rows: list[dict[str, Any]] = []
        for item in listings:
            effective_price = to_effective_price_manwon(
                trade_type_name=item.trade_type_name,
                deal_price_manwon=item.deal_price_manwon,
                rent_price_manwon=item.rent_price_manwon,
                monthly_conversion_rate_pct=conversion_rate,
            )
            if effective_price is None:
                continue
            priced_rows.append(
                {
                    "effective_price_manwon": float(effective_price),
                    "deal_price_text": item.deal_price_text,
                    "article_no": item.article_no,
                    "article_name": item.article_name,
                }
            )

        if not priced_rows:
            continue

        priced_rows.sort(key=lambda row: row["effective_price_manwon"])
        min_row = priced_rows[0]
        max_row = priced_rows[-1]
        avg_price = sum(row["effective_price_manwon"] for row in priced_rows) / len(priced_rows)
        summary = {
            "complex_no": watch.complex_no,
            "complex_name": watch.complex_name,
            "listing_count": len(priced_rows),
            "min_effective_price_manwon": min_row["effective_price_manwon"],
            "max_effective_price_manwon": max_row["effective_price_manwon"],
            "avg_effective_price_manwon": avg_price,
            "min_article_no": min_row["article_no"],
            "max_article_no": max_row["article_no"],
            "min_deal_price_text": min_row["deal_price_text"],
            "max_deal_price_text": max_row["deal_price_text"],
        }
        complex_summaries.append(summary)

        for row in priced_rows:
            overall_rows.append(
                {
                    "complex_no": watch.complex_no,
                    "complex_name": watch.complex_name,
                    **row,
                }
            )

    overall: dict[str, Any] | None = None
    if overall_rows:
        overall_rows.sort(key=lambda row: row["effective_price_manwon"])
        overall_min = overall_rows[0]
        overall_avg = sum(row["effective_price_manwon"] for row in overall_rows) / len(overall_rows)
        overall = {
            "listing_count": len(overall_rows),
            "avg_effective_price_manwon": overall_avg,
            "min_item": overall_min,
        }

    bargains = collect_user_bargains(
        db=db,
        user_id=user_id,
        lookback_days=notification_setting.bargain_lookback_days,
        discount_threshold=notification_setting.bargain_discount_threshold,
        trade_type_name=trade_type_name,
        monthly_conversion_rate_pct=conversion_rate,
    )

    return {
        "trade_type_name": trade_type_name,
        "monthly_conversion_rate_pct": conversion_rate,
        "complex_summaries": complex_summaries,
        "overall": overall,
        "bargains": bargains,
    }


def build_daily_briefing_text(briefing: dict[str, Any]) -> str:
    trade_type_name = briefing.get("trade_type_name") or "매매"
    conversion_rate = float(briefing.get("monthly_conversion_rate_pct") or 0.0)
    summaries = briefing.get("complex_summaries") or []
    overall = briefing.get("overall")
    bargains = briefing.get("bargains") or []

    lines = [
        "[Naver Apt Briefing] 데일리 브리핑",
        f"- 거래유형: {trade_type_name}",
        f"- 전월세전환율: {conversion_rate:.2f}%",
        "",
        "1) 관심 단지 요약",
    ]

    if not summaries:
        lines.append("집계 가능한 최신 매물 데이터가 없습니다.")
    else:
        for idx, summary in enumerate(summaries, start=1):
            complex_label = summary.get("complex_name") or summary.get("complex_no")
            lines.append(
                f"{idx}. {complex_label} | 매물 {summary['listing_count']}건 | "
                f"최저 {summary['min_effective_price_manwon']:.0f}만원 ({summary.get('min_deal_price_text') or '-'}) | "
                f"평균 {summary['avg_effective_price_manwon']:.0f}만원 | "
                f"최고 {summary['max_effective_price_manwon']:.0f}만원 ({summary.get('max_deal_price_text') or '-'})"
            )

    lines.extend(["", "2) 전체 관심단지 요약"])
    if not overall:
        lines.append("전체 집계 가능한 매물이 없습니다.")
    else:
        min_item = overall["min_item"]
        lines.append(
            f"- 전체 최저 매물: {min_item.get('complex_name') or min_item.get('complex_no')} "
            f"/ 매물 {min_item.get('article_no')} / {min_item.get('effective_price_manwon'):.0f}만원 "
            f"({min_item.get('deal_price_text') or '-'})"
        )
        lines.append(f"- 전체 평균 환산가: {overall['avg_effective_price_manwon']:.0f}만원 (총 {overall['listing_count']}건)")

    lines.extend(["", "3) 급매 후보 요약"])
    if not bargains:
        lines.append("오늘 기준 급매 후보가 없습니다.")
    else:
        top = bargains[:10]
        for idx, item in enumerate(top, start=1):
            lines.append(
                f"{idx}. {item.get('complex_name') or item.get('complex_no')} | "
                f"매물 {item.get('article_no')} | "
                f"환산 {float(item.get('effective_price_manwon') or 0):.0f}만원 | "
                f"할인율 {float(item.get('discount_rate') or 0) * 100:.2f}%"
            )
    return "\n".join(lines)


def _already_sent_daily_briefing(db: Session, user_id: UUID, channel: str, dedupe_key: str) -> bool:
    existing = db.scalar(
        select(AlertDispatchLog.id).where(
            AlertDispatchLog.user_id == user_id,
            AlertDispatchLog.channel == channel,
            AlertDispatchLog.alert_type == "daily_briefing",
            AlertDispatchLog.dedupe_key == dedupe_key,
        )
    )
    return existing is not None


def dispatch_user_daily_briefing(
    db: Session,
    settings: Settings,
    user: User,
    notification_setting: UserNotificationSetting,
    briefing_date_key: str,
) -> dict[str, Any]:
    result = {
        "email_sent": 0,
        "telegram_sent": 0,
        "email_reason": "",
        "telegram_reason": "",
        "has_data": False,
    }
    briefing = collect_user_daily_briefing(
        db=db,
        settings=settings,
        user_id=user.id,
        notification_setting=notification_setting,
    )
    if not briefing.get("complex_summaries"):
        result["email_reason"] = "no summary data"
        result["telegram_reason"] = "no summary data"
        return result

    result["has_data"] = True
    message = build_daily_briefing_text(briefing)
    dedupe_key = f"daily_briefing:{briefing_date_key}"
    payload = {
        "briefing_date_key": briefing_date_key,
        "trade_type_name": briefing.get("trade_type_name"),
        "monthly_conversion_rate_pct": briefing.get("monthly_conversion_rate_pct"),
        "complex_count": len(briefing.get("complex_summaries") or []),
        "bargain_count": len(briefing.get("bargains") or []),
    }

    if notification_setting.email_enabled and notification_setting.email_address:
        if _already_sent_daily_briefing(db=db, user_id=user.id, channel="email", dedupe_key=dedupe_key):
            result["email_reason"] = "already sent"
        else:
            ok, reason = send_email_message(
                settings=settings,
                to_email=notification_setting.email_address,
                subject=f"[Naver Apt Briefing] {briefing_date_key} 데일리 브리핑",
                body=message,
            )
            result["email_reason"] = reason
            if ok:
                db.add(
                    AlertDispatchLog(
                        user_id=user.id,
                        channel="email",
                        alert_type="daily_briefing",
                        dedupe_key=dedupe_key,
                        payload=payload,
                    )
                )
                result["email_sent"] = 1

    if notification_setting.telegram_enabled and notification_setting.telegram_chat_id:
        if _already_sent_daily_briefing(db=db, user_id=user.id, channel="telegram", dedupe_key=dedupe_key):
            result["telegram_reason"] = "already sent"
        else:
            ok, reason = send_telegram_message(
                settings=settings,
                chat_id=notification_setting.telegram_chat_id,
                text=message,
            )
            result["telegram_reason"] = reason
            if ok:
                db.add(
                    AlertDispatchLog(
                        user_id=user.id,
                        channel="telegram",
                        alert_type="daily_briefing",
                        dedupe_key=dedupe_key,
                        payload=payload,
                    )
                )
                result["telegram_sent"] = 1

    return result


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
