from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.crawler.naver_client import NaverLandClient
from app.models import CrawlRun, ListingSnapshot
from app.services.parsers import parse_confirmed_date, price_to_manwon
from app.settings import Settings


def ingest_complex_snapshot(
    db: Session,
    settings: Settings,
    complex_no: int,
    page: int = 1,
    max_pages: int = 1,
    real_estate_type: str = "APT:ABYG:JGC",
    trade_type: str = "A1:B1:B2",
) -> dict[str, int]:
    if page < 1:
        raise ValueError("page must be >= 1")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

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
    }
