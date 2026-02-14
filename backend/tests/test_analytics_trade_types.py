import pathlib
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import main
from app.models import UserNotificationSetting
from app.services.analytics import normalize_trade_type_name, to_effective_price_manwon


class FakeDB:
    def __init__(self, setting: object | None = None) -> None:
        self.setting = setting

    def get(self, model, _key):
        if model is UserNotificationSetting:
            return self.setting
        return None


def test_normalize_trade_type_name_all_returns_none() -> None:
    assert normalize_trade_type_name("ALL") is None
    assert normalize_trade_type_name(" all ") is None
    assert normalize_trade_type_name("매매") == "매매"


def test_to_effective_price_monthly_uses_conversion_rate() -> None:
    effective = to_effective_price_manwon(
        trade_type_name="월세",
        deal_price_manwon=30000,
        rent_price_manwon=150,
        monthly_conversion_rate_pct=5.1,
    )
    assert effective == pytest.approx(65294.1176, rel=1e-4)


def test_to_effective_price_sale_uses_deal_price() -> None:
    effective = to_effective_price_manwon(
        trade_type_name="매매",
        deal_price_manwon=98000,
        rent_price_manwon=None,
        monthly_conversion_rate_pct=5.1,
    )
    assert effective == 98000.0


def test_resolve_trade_type_and_conversion_uses_user_override_when_missing_query() -> None:
    setting = SimpleNamespace(
        interest_trade_type="월세",
        monthly_rent_conversion_rate_pct=4.2,
    )
    db = FakeDB(setting=setting)
    user = SimpleNamespace(id=uuid4())

    trade_type_name, conversion_rate = main._resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=None,
        requested_monthly_conversion_rate_pct=None,
        user=user,
    )

    assert trade_type_name == "월세"
    assert conversion_rate == 4.2


def test_resolve_trade_type_and_conversion_query_value_overrides_user_setting() -> None:
    setting = SimpleNamespace(
        interest_trade_type="전세",
        monthly_rent_conversion_rate_pct=4.3,
    )
    db = FakeDB(setting=setting)
    user = SimpleNamespace(id=uuid4())

    trade_type_name, conversion_rate = main._resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name="월세",
        requested_monthly_conversion_rate_pct=5.8,
        user=user,
    )

    assert trade_type_name == "월세"
    assert conversion_rate == 5.8


def test_resolve_trade_type_and_conversion_defaults_to_sale_and_system_rate() -> None:
    db = FakeDB(setting=None)

    trade_type_name, conversion_rate = main._resolve_trade_type_and_conversion(
        db=db,
        requested_trade_type_name=None,
        requested_monthly_conversion_rate_pct=None,
        user=None,
    )

    assert trade_type_name == "매매"
    assert conversion_rate == main.settings.jeonse_monthly_conversion_rate_default


def test_update_notification_setting_rejects_invalid_interest_trade_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        main._normalize_interest_trade_type("투자")
    assert exc_info.value.status_code == 400
