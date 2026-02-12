import pathlib
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import main
from app.models import BillingCheckoutSession, UserSubscription
from app.services.billing import (
    BillingError,
    complete_dummy_checkout_session,
    create_dummy_checkout_session,
    get_user_entitlements,
)


class FakeBillingDB:
    def __init__(self) -> None:
        self.subscriptions: dict[tuple[type[UserSubscription], object], UserSubscription] = {}
        self.scalar_result = None

    def get(self, model, key):
        return self.subscriptions.get((model, key))

    def add(self, obj):
        if isinstance(obj, UserSubscription):
            self.subscriptions[(UserSubscription, obj.user_id)] = obj

    def flush(self) -> None:
        return None

    def scalar(self, _stmt):
        return self.scalar_result


def test_get_user_entitlements_creates_default_free_subscription() -> None:
    db = FakeBillingDB()
    user_id = uuid4()

    entitlements = get_user_entitlements(db=db, user_id=user_id)

    assert entitlements["plan_code"] == "FREE"
    assert entitlements["limits"]["watch_complex_limit"] == 3


def test_create_dummy_checkout_session_rejects_non_paid_plan() -> None:
    db = FakeBillingDB()

    with pytest.raises(BillingError) as exc_info:
        create_dummy_checkout_session(db=db, user_id=uuid4(), plan_code="FREE")

    assert exc_info.value.status_code == 400


def test_complete_dummy_checkout_session_promotes_user_to_pro() -> None:
    db = FakeBillingDB()
    user_id = uuid4()
    checkout = BillingCheckoutSession(
        user_id=user_id,
        provider="dummy",
        plan_code="PRO",
        status="PENDING",
        checkout_token="dummy-token",
        amount_krw=9900,
        currency="KRW",
        checkout_payload={"flow": "dummy"},
    )
    db.scalar_result = checkout

    completed_session, subscription, changed = complete_dummy_checkout_session(
        db=db,
        user_id=user_id,
        checkout_token="dummy-token",
    )

    assert changed is True
    assert completed_session.status == "COMPLETED"
    assert subscription.plan_code == "PRO"
    assert subscription.status == "ACTIVE"


def test_me_add_watch_complex_maps_billing_error_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_enforce_watch_complex_limit(*, db, user_id):
        raise BillingError("무료 플랜 제한", status_code=403)

    monkeypatch.setattr(main, "enforce_watch_complex_limit", fake_enforce_watch_complex_limit)

    with pytest.raises(HTTPException) as exc_info:
        main.me_add_watch_complex(
            complex_no=2977,
            complex_name="테스트",
            sido_name=None,
            gugun_name=None,
            dong_name=None,
            current_user=SimpleNamespace(id=uuid4()),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403


def test_analytics_compare_maps_billing_error_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_enforce_compare_limit(*, db, user_id, requested_complex_count):
        raise BillingError("무료 플랜 비교 제한", status_code=403)

    monkeypatch.setattr(main, "enforce_compare_limit", fake_enforce_compare_limit)

    with pytest.raises(HTTPException) as exc_info:
        main.analytics_compare(
            complex_nos=[1, 2, 3],
            days=30,
            trade_type_name=None,
            current_user=SimpleNamespace(id=uuid4()),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403
