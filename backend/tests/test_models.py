import pathlib
import sys

from sqlalchemy import BigInteger, Boolean, String

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.models import BillingCheckoutSession, ListingSnapshot, UserSubscription


def test_listing_snapshot_article_no_uses_bigint() -> None:
    column_type = ListingSnapshot.__table__.c.article_no.type
    assert isinstance(column_type, BigInteger)


def test_user_subscription_schema_has_plan_and_status_columns() -> None:
    table = UserSubscription.__table__.c
    assert isinstance(table.plan_code.type, String)
    assert isinstance(table.status.type, String)
    assert isinstance(table.cancel_at_period_end.type, Boolean)


def test_billing_checkout_session_schema_has_dummy_flow_fields() -> None:
    table = BillingCheckoutSession.__table__.c
    assert isinstance(table.plan_code.type, String)
    assert isinstance(table.status.type, String)
    assert isinstance(table.provider.type, String)
    assert table.checkout_token.unique is True
