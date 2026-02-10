from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from app.models import CrawlRun, ListingSnapshot


def fetch_complex_trend(
    db: Session,
    complex_no: int,
    days: int = 30,
    trade_type_name: str | None = None,
) -> list[dict[str, float | int | str]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt: Select = (
        select(
            func.date(ListingSnapshot.observed_at).label("date"),
            func.avg(ListingSnapshot.deal_price_manwon).label("avg_price"),
            func.min(ListingSnapshot.deal_price_manwon).label("min_price"),
            func.max(ListingSnapshot.deal_price_manwon).label("max_price"),
            func.count(ListingSnapshot.id).label("listing_count"),
        )
        .where(
            ListingSnapshot.complex_no == complex_no,
            ListingSnapshot.observed_at >= since,
            ListingSnapshot.deal_price_manwon.is_not(None),
        )
        .group_by(func.date(ListingSnapshot.observed_at))
        .order_by(func.date(ListingSnapshot.observed_at))
    )

    if trade_type_name:
        stmt = stmt.where(ListingSnapshot.trade_type_name == trade_type_name)

    rows = db.execute(stmt).all()
    return [
        {
            "date": row.date.isoformat(),
            "avg_price_manwon": float(row.avg_price) if row.avg_price is not None else 0,
            "min_price_manwon": int(row.min_price) if row.min_price is not None else 0,
            "max_price_manwon": int(row.max_price) if row.max_price is not None else 0,
            "listing_count": int(row.listing_count),
        }
        for row in rows
    ]


def fetch_compare_trend(
    db: Session,
    complex_nos: list[int],
    days: int = 30,
    trade_type_name: str | None = None,
) -> dict[int, list[dict[str, float | int | str]]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt: Select = (
        select(
            ListingSnapshot.complex_no,
            func.date(ListingSnapshot.observed_at).label("date"),
            func.avg(ListingSnapshot.deal_price_manwon).label("avg_price"),
            func.count(ListingSnapshot.id).label("listing_count"),
        )
        .where(
            ListingSnapshot.complex_no.in_(complex_nos),
            ListingSnapshot.observed_at >= since,
            ListingSnapshot.deal_price_manwon.is_not(None),
        )
        .group_by(ListingSnapshot.complex_no, func.date(ListingSnapshot.observed_at))
        .order_by(ListingSnapshot.complex_no, func.date(ListingSnapshot.observed_at))
    )

    if trade_type_name:
        stmt = stmt.where(ListingSnapshot.trade_type_name == trade_type_name)

    rows = db.execute(stmt).all()
    result: dict[int, list[dict[str, float | int | str]]] = {complex_no: [] for complex_no in complex_nos}

    for row in rows:
        result[row.complex_no].append(
            {
                "date": row.date.isoformat(),
                "avg_price_manwon": float(row.avg_price) if row.avg_price is not None else 0,
                "listing_count": int(row.listing_count),
            }
        )

    return result


def detect_bargains(
    db: Session,
    complex_no: int,
    lookback_days: int = 30,
    discount_threshold: float = 0.08,
    trade_type_name: str | None = None,
) -> list[dict[str, float | int | str | None]]:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    baseline_stmt: Select = select(ListingSnapshot.deal_price_manwon).where(
        ListingSnapshot.complex_no == complex_no,
        ListingSnapshot.observed_at >= since,
        ListingSnapshot.deal_price_manwon.is_not(None),
    )
    if trade_type_name:
        baseline_stmt = baseline_stmt.where(ListingSnapshot.trade_type_name == trade_type_name)

    baseline_prices = [int(row[0]) for row in db.execute(baseline_stmt).all() if row[0] is not None]
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
        ListingSnapshot.deal_price_manwon.is_not(None),
    )
    if trade_type_name:
        latest_list_stmt = latest_list_stmt.where(ListingSnapshot.trade_type_name == trade_type_name)

    candidates = db.scalars(latest_list_stmt).all()
    results: list[dict[str, float | int | str | None]] = []

    for item in candidates:
        if item.deal_price_manwon is None:
            continue
        discount_rate = (baseline_median - float(item.deal_price_manwon)) / baseline_median
        if discount_rate >= discount_threshold:
            results.append(
                {
                    "article_no": item.article_no,
                    "article_name": item.article_name,
                    "trade_type_name": item.trade_type_name,
                    "deal_price_text": item.deal_price_text,
                    "deal_price_manwon": item.deal_price_manwon,
                    "baseline_median_manwon": baseline_median,
                    "discount_rate": round(discount_rate, 4),
                    "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                }
            )

    results.sort(key=lambda row: row["discount_rate"], reverse=True)
    return results
