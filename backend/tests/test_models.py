import pathlib
import sys

from sqlalchemy import BigInteger

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.models import ListingSnapshot


def test_listing_snapshot_article_no_uses_bigint() -> None:
    column_type = ListingSnapshot.__table__.c.article_no.type
    assert isinstance(column_type, BigInteger)
