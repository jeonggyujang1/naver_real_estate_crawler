import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.notifier import build_bargain_alert_text, send_email_message, send_telegram_message
from app.settings import Settings


def test_build_bargain_alert_text_contains_core_fields() -> None:
    text = build_bargain_alert_text(
        [
            {
                "complex_no": 12345,
                "article_no": 999,
                "article_name": "101동 15층",
                "trade_type_name": "매매",
                "deal_price_text": "9억 5,000",
                "discount_rate": 0.1234,
            }
        ]
    )
    assert "12345" in text
    assert "999" in text
    assert "12.34%" in text


def test_send_email_message_disabled_returns_reason() -> None:
    settings = Settings(smtp_enabled=False)
    ok, reason = send_email_message(
        settings=settings,
        to_email="user@example.com",
        subject="test",
        body="test body",
    )
    assert ok is False
    assert reason == "SMTP disabled"


def test_send_telegram_message_disabled_returns_reason() -> None:
    settings = Settings(telegram_enabled=False)
    ok, reason = send_telegram_message(settings=settings, chat_id="1234", text="hello")
    assert ok is False
    assert reason == "Telegram disabled"
