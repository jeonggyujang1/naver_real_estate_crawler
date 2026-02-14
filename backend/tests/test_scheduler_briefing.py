import pathlib
import sys
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services import scheduler as scheduler_module
from app.services.alerts import build_daily_briefing_text


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeDB:
    def __init__(self, watcher_user_ids=None):
        self.watcher_user_ids = watcher_user_ids or []
        self.users = {}
        self.notification_settings = {}
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def scalars(self, _stmt):
        return FakeScalarResult(self.watcher_user_ids)

    def get(self, model, key):
        if model is scheduler_module.User:
            return self.users.get(key)
        if model is scheduler_module.UserNotificationSetting:
            return self.notification_settings.get(key)
        if model is scheduler_module.SchedulerConfig:
            return None
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _build_settings():
    return SimpleNamespace(
        scheduler_enabled=True,
        scheduler_timezone="Asia/Seoul",
        scheduler_times_csv="09:00,18:00",
        scheduler_poll_seconds=20,
        scheduler_complex_nos_csv="2977",
        crawler_reuse_window_hours=12,
        jeonse_monthly_conversion_rate_default=5.1,
    )


def test_dispatch_daily_briefing_only_first_time(monkeypatch) -> None:
    settings = _build_settings()
    scheduler = scheduler_module.CrawlScheduler(settings=settings)
    timezone = ZoneInfo("Asia/Seoul")

    active_user_id = uuid4()
    inactive_user_id = uuid4()
    db = FakeDB(watcher_user_ids=[active_user_id, inactive_user_id])
    db.users[active_user_id] = SimpleNamespace(id=active_user_id, is_active=True)
    db.users[inactive_user_id] = SimpleNamespace(id=inactive_user_id, is_active=False)
    db.notification_settings[active_user_id] = SimpleNamespace(
        email_enabled=True,
        telegram_enabled=False,
    )

    calls = []

    def fake_dispatch_user_daily_briefing(**kwargs):
        calls.append(kwargs["user"].id)
        return {"email_sent": 1, "telegram_sent": 0}

    monkeypatch.setattr(scheduler_module, "dispatch_user_daily_briefing", fake_dispatch_user_daily_briefing)

    scheduler._dispatch_daily_briefings_for_first_time(
        db=db,
        timezone=timezone,
        hhmm="09:00",
        times={"09:00", "18:00"},
    )

    assert calls == [active_user_id]
    assert db.commits == 1


def test_dispatch_daily_briefing_skips_non_first_time(monkeypatch) -> None:
    settings = _build_settings()
    scheduler = scheduler_module.CrawlScheduler(settings=settings)
    timezone = ZoneInfo("Asia/Seoul")
    user_id = uuid4()
    db = FakeDB(watcher_user_ids=[user_id])
    db.users[user_id] = SimpleNamespace(id=user_id, is_active=True)
    db.notification_settings[user_id] = SimpleNamespace(
        email_enabled=True,
        telegram_enabled=False,
    )

    calls = []

    def fake_dispatch_user_daily_briefing(**kwargs):
        calls.append(kwargs["user"].id)
        return {"email_sent": 1, "telegram_sent": 0}

    monkeypatch.setattr(scheduler_module, "dispatch_user_daily_briefing", fake_dispatch_user_daily_briefing)

    scheduler._dispatch_daily_briefings_for_first_time(
        db=db,
        timezone=timezone,
        hhmm="18:00",
        times={"09:00", "18:00"},
    )

    assert calls == []
    assert db.commits == 0


def test_run_if_due_calls_daily_briefing_dispatch(monkeypatch) -> None:
    settings = _build_settings()
    scheduler = scheduler_module.CrawlScheduler(settings=settings)
    db = FakeDB()

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 14, 9, 0, tzinfo=tz)

    ingest_calls = []
    alert_calls = []
    briefing_calls = []

    monkeypatch.setattr(scheduler_module, "datetime", FixedDateTime)
    monkeypatch.setattr(scheduler_module, "get_session_factory", lambda: lambda: db)
    monkeypatch.setattr(
        scheduler,
        "_load_runtime_config",
        lambda db: {
            "enabled": True,
            "timezone": "Asia/Seoul",
            "times": {"09:00", "18:00"},
            "poll_seconds": 20,
            "complex_nos": [2977],
            "reuse_bucket_hours": 12,
        },
    )
    monkeypatch.setattr(
        scheduler_module,
        "ingest_complex_snapshot",
        lambda **kwargs: ingest_calls.append(kwargs["complex_no"]) or {"crawl_run_id": 1},
    )
    monkeypatch.setattr(
        scheduler,
        "_dispatch_alerts_for_complex",
        lambda db, complex_no: alert_calls.append(complex_no),
    )
    monkeypatch.setattr(
        scheduler,
        "_dispatch_daily_briefings_for_first_time",
        lambda db, timezone, hhmm, times: briefing_calls.append((hhmm, sorted(times))),
    )

    poll_seconds = scheduler._run_if_due()

    assert poll_seconds == 20
    assert ingest_calls == [2977]
    assert alert_calls == [2977]
    assert briefing_calls == [("09:00", ["09:00", "18:00"])]
    assert db.closed is True


def test_build_daily_briefing_text_contains_summary_sections() -> None:
    text = build_daily_briefing_text(
        {
            "trade_type_name": "매매",
            "monthly_conversion_rate_pct": 5.1,
            "complex_summaries": [
                {
                    "complex_no": 2977,
                    "complex_name": "래미안 대치팰리스",
                    "listing_count": 3,
                    "min_effective_price_manwon": 220000,
                    "avg_effective_price_manwon": 230000,
                    "max_effective_price_manwon": 250000,
                    "min_deal_price_text": "22억",
                    "max_deal_price_text": "25억",
                }
            ],
            "overall": {
                "listing_count": 3,
                "avg_effective_price_manwon": 230000,
                "min_item": {
                    "complex_no": 2977,
                    "complex_name": "래미안 대치팰리스",
                    "article_no": 123456789,
                    "effective_price_manwon": 220000,
                    "deal_price_text": "22억",
                },
            },
            "bargains": [
                {
                    "complex_no": 2977,
                    "complex_name": "래미안 대치팰리스",
                    "article_no": 123456789,
                    "effective_price_manwon": 220000,
                    "discount_rate": 0.12,
                }
            ],
        }
    )

    assert "1) 관심 단지 요약" in text
    assert "2) 전체 관심단지 요약" in text
    assert "3) 급매 후보 요약" in text
    assert "래미안 대치팰리스" in text
