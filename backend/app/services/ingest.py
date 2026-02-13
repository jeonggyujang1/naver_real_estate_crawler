from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crawler.naver_client import NaverLandClient
from app.models import CrawlRun, ListingSnapshot
from app.services.parsers import parse_confirmed_date, price_to_manwon
from app.settings import Settings


def _resolve_time_bucket(now: datetime, window_hours: int) -> tuple[datetime, datetime]:
    hour = (now.hour // window_hours) * window_hours
    bucket_start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    bucket_end = bucket_start + timedelta(hours=window_hours)
    return bucket_start, bucket_end


def ingest_complex_snapshot(
    db: Session,
    settings: Settings,
    complex_no: int,
    page: int = 1,
    max_pages: int = 1,
    real_estate_type: str = "APT:ABYG:JGC",
    trade_type: str = "A1:B1:B2",
    reuse_window_hours: int | None = None,
) -> dict[str, int]:
    if page < 1:
        raise ValueError("page must be >= 1")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    resolved_reuse_window_hours = settings.crawler_reuse_window_hours if reuse_window_hours is None else reuse_window_hours
    if resolved_reuse_window_hours > 0:
        now_utc = datetime.now(timezone.utc)
        bucket_start, bucket_end = _resolve_time_bucket(now=now_utc, window_hours=resolved_reuse_window_hours)
        existing_run = db.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.complex_no == complex_no,
                CrawlRun.status == "SUCCESS",
                CrawlRun.completed_at.is_not(None),
                CrawlRun.completed_at >= bucket_start,
                CrawlRun.completed_at < bucket_end,
            )
            .order_by(CrawlRun.completed_at.desc())
            .limit(1)
        )
        if existing_run is not None:
            listing_count = int(
                db.scalar(
                    select(func.count(ListingSnapshot.id)).where(ListingSnapshot.crawl_run_id == existing_run.id)
                )
                or 0
            )
            return {
                "crawl_run_id": existing_run.id,
                "complex_no": complex_no,
                "listing_count": listing_count,
                "pages_fetched": 0,
                "reused": 1,
            }

    client = NaverLandClient(settings=settings)
    first_payload = client.fetch_complex_articles(
        complex_no=complex_no,
        page=page,
        real_estate_type=real_estate_type,
        trade_type=trade_type,
    )

    crawl_run = CrawlRun(complex_no=complex_no, status="SUCCESS", raw_payload=first_payload)
    db.add(crawl_run)
    db.flush()

    listing_count = 0
    pages_fetched = 0
    seen_article_nos: set[int] = set()

    for current_page in range(page, page + max_pages):
        payload = first_payload
        if current_page != page:
            payload = client.fetch_complex_articles(
                complex_no=complex_no,
                page=current_page,
                real_estate_type=real_estate_type,
                trade_type=trade_type,
            )

        article_list: list[dict[str, Any]] = payload.get("articleList", [])
        if not article_list:
            break
        pages_fetched += 1

        for article in article_list:
            article_no = article.get("articleNo")
            if article_no is None:
                continue
            try:
                normalized_article_no = int(article_no)
            except (TypeError, ValueError):
                continue
            if normalized_article_no in seen_article_nos:
                continue
            seen_article_nos.add(normalized_article_no)

            listing = ListingSnapshot(
                crawl_run_id=crawl_run.id,
                complex_no=complex_no,
                article_no=normalized_article_no,
                article_name=article.get("articleName"),
                trade_type_name=article.get("tradeTypeName"),
                deal_price_text=article.get("dealOrWarrantPrc"),
                rent_price_text=article.get("rentPrc"),
                deal_price_manwon=price_to_manwon(article.get("dealOrWarrantPrc")),
                rent_price_manwon=price_to_manwon(article.get("rentPrc")),
                area_m2=article.get("area1"),
                floor_info=article.get("floorInfo"),
                direction=article.get("direction"),
                confirmed_date=parse_confirmed_date(article.get("articleConfirmYmd")),
                listing_meta=article,
            )
            db.add(listing)
            listing_count += 1

    crawl_run.completed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "crawl_run_id": crawl_run.id,
        "complex_no": complex_no,
        "listing_count": listing_count,
        "pages_fetched": pages_fetched,
        "reused": 0,
    }
