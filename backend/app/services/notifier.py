import json
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.request import Request, urlopen

from app.settings import Settings


def build_bargain_alert_text(items: list[dict[str, Any]]) -> str:
    lines = ["[급매 알림] 관심 단지에서 할인율 기준을 충족한 매물을 찾았습니다.", ""]
    for idx, item in enumerate(items, start=1):
        complex_label = item.get("complex_name") or item.get("complex_no") or "-"
        article_no = item.get("article_no") or "-"
        article_name = item.get("article_name") or "-"
        trade_type = item.get("trade_type_name") or "-"
        deal_price = item.get("deal_price_text") or "-"
        discount_rate = float(item.get("discount_rate") or 0.0) * 100.0
        lines.append(
            f"{idx}. 단지 {complex_label} | 매물 {article_no} ({article_name}) | {trade_type} | "
            f"가격 {deal_price} | 할인율 {discount_rate:.2f}%"
        )
    lines.extend(["", "※ 본 알림은 참고용이며 실제 거래 전 상세 확인이 필요합니다."])
    return "\n".join(lines)


def send_email_message(
    settings: Settings,
    to_email: str,
    subject: str,
    body: str,
) -> tuple[bool, str]:
    if not settings.smtp_enabled:
        return False, "SMTP disabled"
    if not settings.smtp_host or not settings.smtp_sender_email:
        return False, "SMTP config missing"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_sender_email
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        return False, f"email send failed: {exc}"
    return True, "ok"


def send_telegram_message(
    settings: Settings,
    chat_id: str,
    text: str,
) -> tuple[bool, str]:
    if not settings.telegram_enabled:
        return False, "Telegram disabled"
    if not settings.telegram_bot_token:
        return False, "Telegram bot token missing"

    endpoint = f"{settings.telegram_api_base_url}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    request = Request(
        url=endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            if not response_data.get("ok", False):
                return False, f"telegram send failed: {response_data}"
    except Exception as exc:
        return False, f"telegram send failed: {exc}"
    return True, "ok"
