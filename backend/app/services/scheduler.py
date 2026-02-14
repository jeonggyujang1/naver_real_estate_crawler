import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import SchedulerConfig, User, UserNotificationSetting, UserWatchComplex
from app.services.alerts import collect_user_bargains, dispatch_user_bargain_alerts
from app.services.ingest import ingest_complex_snapshot
from app.settings import Settings

logger = logging.getLogger(__name__)


class CrawlScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._executed_keys: set[str] = set()

    @staticmethod
    def _parse_times(raw: str) -> set[str]:
        parsed: set[str] = set()
        for token in raw.split(","):
            value = token.strip()
            if len(value) == 5 and value[2] == ":":
                parsed.add(value)
        return parsed

    @staticmethod
    def _parse_complex_nos(raw: str) -> list[int]:
        result: list[int] = []
        for token in raw.split(","):
            value = token.strip()
            if value.isdigit():
                result.append(int(value))
        return result

    def _load_runtime_config(self, db: Session) -> dict[str, object]:
        row = db.get(SchedulerConfig, 1)
        enabled = row.enabled if row is not None else self.settings.scheduler_enabled
        timezone_name = row.timezone if row is not None else self.settings.scheduler_timezone
        times_csv = row.times_csv if row is not None else self.settings.scheduler_times_csv
        poll_seconds = row.poll_seconds if row is not None else self.settings.scheduler_poll_seconds
        reuse_bucket_hours = row.reuse_bucket_hours if row is not None else self.settings.crawler_reuse_window_hours

        watch_complex_nos = db.scalars(
            select(UserWatchComplex.complex_no)
            .where(UserWatchComplex.enabled.is_(True))
            .distinct()
            .order_by(UserWatchComplex.complex_no.asc())
        ).all()

        fallback_complex_nos = self._parse_complex_nos(self.settings.scheduler_complex_nos_csv)
        complex_nos = watch_complex_nos or fallback_complex_nos
        return {
            "enabled": enabled,
            "timezone": timezone_name,
            "times": self._parse_times(times_csv),
            "poll_seconds": max(5, int(poll_seconds)),
            "complex_nos": complex_nos,
            "reuse_bucket_hours": max(0, int(reuse_bucket_hours)),
        }

    async def run(self) -> None:
        logger.info("Scheduler started.")
        while True:
            # Crawler/DB flow is blocking I/O; run it in a worker thread to keep the event loop responsive.
            poll_seconds = await asyncio.to_thread(self._run_if_due)
            await asyncio.sleep(poll_seconds)

    def _dispatch_alerts_for_complex(self, db: Session, complex_no: int) -> None:
        watcher_user_ids = db.scalars(
            select(UserWatchComplex.user_id).where(
                UserWatchComplex.complex_no == complex_no,
                UserWatchComplex.enabled.is_(True),
            )
        ).all()
        for user_id in set(watcher_user_ids):
            user = db.get(User, user_id)
            if user is None or not user.is_active:
                continue
            setting = db.get(UserNotificationSetting, user_id)
            if setting is None or not setting.bargain_alert_enabled:
                continue

            items = collect_user_bargains(
                db=db,
                user_id=user_id,
                lookback_days=setting.bargain_lookback_days,
                discount_threshold=setting.bargain_discount_threshold,
                only_complex_no=complex_no,
            )
            dispatch_result = dispatch_user_bargain_alerts(
                db=db,
                settings=self.settings,
                user=user,
                notification_setting=setting,
                items=items,
            )
            if dispatch_result["email_sent"] or dispatch_result["telegram_sent"]:
                db.commit()
                logger.info(
                    "Scheduled bargain alerts sent. complex_no=%s user_id=%s email=%s telegram=%s",
                    complex_no,
                    user_id,
                    dispatch_result["email_sent"],
                    dispatch_result["telegram_sent"],
                )

    def _run_if_due(self) -> int:
        db = get_session_factory()()
        try:
            config = self._load_runtime_config(db=db)
            enabled = bool(config["enabled"])
            times = config["times"]
            complex_nos = config["complex_nos"]
            poll_seconds = int(config["poll_seconds"])
            timezone_name = str(config["timezone"])
            reuse_bucket_hours = int(config["reuse_bucket_hours"])

            if not enabled or not times or not complex_nos:
                return poll_seconds

            try:
                timezone = ZoneInfo(timezone_name)
            except Exception:
                timezone = ZoneInfo(self.settings.scheduler_timezone)

            now = datetime.now(timezone)
            hhmm = now.strftime("%H:%M")
            if hhmm not in times:
                return poll_seconds

            run_key = now.strftime("%Y-%m-%d %H:%M")
            if run_key in self._executed_keys:
                return poll_seconds

            self._executed_keys.add(run_key)
            if len(self._executed_keys) > 1000:
                today_prefix = now.strftime("%Y-%m-%d ")
                self._executed_keys = {key for key in self._executed_keys if key.startswith(today_prefix)}

            logger.info(
                "Scheduler tick. timezone=%s times=%s complex_count=%s reuse_bucket_hours=%s",
                timezone.key if hasattr(timezone, "key") else timezone_name,
                sorted(times),
                len(complex_nos),
                reuse_bucket_hours,
            )

            for complex_no in complex_nos:
                try:
                    result = ingest_complex_snapshot(
                        db=db,
                        settings=self.settings,
                        complex_no=complex_no,
                        page=1,
                        max_pages=10,
                        reuse_window_hours=reuse_bucket_hours,
                    )
                    logger.info("Scheduled ingest success: %s", result)
                    try:
                        self._dispatch_alerts_for_complex(db=db, complex_no=complex_no)
                    except Exception:
                        db.rollback()
                        logger.exception("Scheduled alert dispatch failed. complex_no=%s", complex_no)
                except Exception:
                    db.rollback()
                    logger.exception("Scheduled ingest failed. complex_no=%s", complex_no)
            return poll_seconds
        finally:
            db.close()
