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
    real_estate_type: str = "APT:ABYG:JGC",
    trade_type: str = "A1:B1:B2",
) -> dict[str, int]:
    client = NaverLandClient(settings=settings)
    payload = client.fetch_complex_articles(
        complex_no=complex_no,
        page=page,
        real_estate_type=real_estate_type,
        trade_type=trade_type,
    )

    crawl_run = CrawlRun(complex_no=complex_no, status="SUCCESS", raw_payload=payload)
    db.add(crawl_run)
    db.flush()

    article_list: list[dict[str, Any]] = payload.get("articleList", [])
    listing_count = 0

    for article in article_list:
        article_no = article.get("articleNo")
        if article_no is None:
            continue

        listing = ListingSnapshot(
            crawl_run_id=crawl_run.id,
            complex_no=complex_no,
            article_no=article_no,
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
    }
