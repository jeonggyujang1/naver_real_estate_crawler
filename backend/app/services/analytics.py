from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from app.models import CrawlRun, ListingSnapshot


def normalize_trade_type_name(trade_type_name: str | None) -> str | None:
    if trade_type_name is None:
        return None
    normalized = trade_type_name.strip()
    if not normalized:
        return None
    if normalized.upper() == "ALL":
        return None
    return normalized


def to_effective_price_manwon(
    *,
    trade_type_name: str | None,
    deal_price_manwon: int | None,
    rent_price_manwon: int | None,
    monthly_conversion_rate_pct: float,
) -> float | None:
    if monthly_conversion_rate_pct <= 0:
        return None

    normalized_trade_type = (trade_type_name or "").strip()
    if normalized_trade_type == "월세":
        if deal_price_manwon is None or rent_price_manwon is None:
            return None
        return float(deal_price_manwon) + (float(rent_price_manwon) * 12.0 / (monthly_conversion_rate_pct / 100.0))

    if deal_price_manwon is None:
        return None
    return float(deal_price_manwon)


def fetch_complex_trend(
    db: Session,
    complex_no: int,
    days: int = 30,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float = 5.1,
) -> list[dict[str, float | int | str]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    normalized_trade_type = normalize_trade_type_name(trade_type_name)

    stmt: Select = (
        select(
            ListingSnapshot.observed_at,
            ListingSnapshot.trade_type_name,
            ListingSnapshot.deal_price_manwon,
            ListingSnapshot.rent_price_manwon,
        )
        .where(
            ListingSnapshot.complex_no == complex_no,
            ListingSnapshot.observed_at >= since,
        )
    )

    if normalized_trade_type:
        stmt = stmt.where(ListingSnapshot.trade_type_name == normalized_trade_type)

    rows = db.execute(stmt).all()
    prices_by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        effective_price = to_effective_price_manwon(
            trade_type_name=row.trade_type_name,
            deal_price_manwon=row.deal_price_manwon,
            rent_price_manwon=row.rent_price_manwon,
            monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        )
        if effective_price is None:
            continue
        prices_by_date[row.observed_at.date().isoformat()].append(effective_price)

    series: list[dict[str, float | int | str]] = []
    for date_key in sorted(prices_by_date.keys()):
        prices = prices_by_date[date_key]
        series.append(
            {
                "date": date_key,
                "avg_price_manwon": round(sum(prices) / len(prices), 2),
                "min_price_manwon": round(min(prices), 2),
                "max_price_manwon": round(max(prices), 2),
                "listing_count": len(prices),
            }
        )
    return series


def fetch_compare_trend(
    db: Session,
    complex_nos: list[int],
    days: int = 30,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float = 5.1,
) -> dict[int, list[dict[str, float | int | str]]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    normalized_trade_type = normalize_trade_type_name(trade_type_name)

    stmt: Select = (
        select(
            ListingSnapshot.complex_no,
            ListingSnapshot.observed_at,
            ListingSnapshot.trade_type_name,
            ListingSnapshot.deal_price_manwon,
            ListingSnapshot.rent_price_manwon,
        )
        .where(
            ListingSnapshot.complex_no.in_(complex_nos),
            ListingSnapshot.observed_at >= since,
        )
    )

    if normalized_trade_type:
        stmt = stmt.where(ListingSnapshot.trade_type_name == normalized_trade_type)

    rows = db.execute(stmt).all()
    grouped: dict[int, dict[str, list[float]]] = {complex_no: defaultdict(list) for complex_no in complex_nos}

    for row in rows:
        effective_price = to_effective_price_manwon(
            trade_type_name=row.trade_type_name,
            deal_price_manwon=row.deal_price_manwon,
            rent_price_manwon=row.rent_price_manwon,
            monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        )
        if effective_price is None:
            continue
        grouped[int(row.complex_no)][row.observed_at.date().isoformat()].append(effective_price)

    result: dict[int, list[dict[str, float | int | str]]] = {complex_no: [] for complex_no in complex_nos}
    for complex_no in complex_nos:
        for date_key in sorted(grouped[complex_no].keys()):
            prices = grouped[complex_no][date_key]
            result[complex_no].append(
                {
                    "date": date_key,
                    "avg_price_manwon": round(sum(prices) / len(prices), 2),
                    "listing_count": len(prices),
                }
            )

    return result


def detect_bargains(
    db: Session,
    complex_no: int,
    lookback_days: int = 30,
    discount_threshold: float = 0.08,
    trade_type_name: str | None = None,
    monthly_conversion_rate_pct: float = 5.1,
) -> list[dict[str, float | int | str | None]]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    normalized_trade_type = normalize_trade_type_name(trade_type_name)

    baseline_stmt: Select = select(
        ListingSnapshot.trade_type_name,
        ListingSnapshot.deal_price_manwon,
        ListingSnapshot.rent_price_manwon,
    ).where(
        ListingSnapshot.complex_no == complex_no,
        ListingSnapshot.observed_at >= since,
    )
    if normalized_trade_type:
        baseline_stmt = baseline_stmt.where(ListingSnapshot.trade_type_name == normalized_trade_type)

    baseline_prices = [
        value
        for value in [
            to_effective_price_manwon(
                trade_type_name=row.trade_type_name,
                deal_price_manwon=row.deal_price_manwon,
                rent_price_manwon=row.rent_price_manwon,
                monthly_conversion_rate_pct=monthly_conversion_rate_pct,
            )
            for row in db.execute(baseline_stmt).all()
        ]
        if value is not None
    ]
    if len(baseline_prices) < 5:
        return []

    baseline_median = float(median(baseline_prices))

    latest_run_stmt: Select = (
        select(CrawlRun.id)
        .where(CrawlRun.complex_no == complex_no, CrawlRun.status == "SUCCESS")
        .order_by(desc(CrawlRun.started_at))
        .limit(1)
    )
    latest_run_id = db.scalar(latest_run_stmt)
    if latest_run_id is None:
        return []

    latest_list_stmt: Select = select(ListingSnapshot).where(
        ListingSnapshot.crawl_run_id == latest_run_id,
    )
    if normalized_trade_type:
        latest_list_stmt = latest_list_stmt.where(ListingSnapshot.trade_type_name == normalized_trade_type)

    candidates = db.scalars(latest_list_stmt).all()
    results: list[dict[str, float | int | str | None]] = []

    for item in candidates:
        effective_price = to_effective_price_manwon(
            trade_type_name=item.trade_type_name,
            deal_price_manwon=item.deal_price_manwon,
            rent_price_manwon=item.rent_price_manwon,
            monthly_conversion_rate_pct=monthly_conversion_rate_pct,
        )
        if effective_price is None:
            continue
        discount_rate = (baseline_median - float(effective_price)) / baseline_median
        if discount_rate >= discount_threshold:
            results.append(
                {
                    "article_no": item.article_no,
                    "article_name": item.article_name,
                    "trade_type_name": item.trade_type_name,
                    "deal_price_text": item.deal_price_text,
                    "deal_price_manwon": item.deal_price_manwon,
                    "rent_price_manwon": item.rent_price_manwon,
                    "effective_price_manwon": round(effective_price, 2),
                    "monthly_conversion_rate_pct": monthly_conversion_rate_pct,
                    "baseline_median_manwon": baseline_median,
                    "discount_rate": round(discount_rate, 4),
                    "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                }
            )

    results.sort(key=lambda row: row["discount_rate"], reverse=True)
    return results
