import asyncio
import logging

from app.services.scheduler import CrawlScheduler
from app.settings import get_settings

logger = logging.getLogger(__name__)


async def run_scheduler_worker() -> None:
    settings = get_settings()
    logger.info(
        "Starting scheduler worker. timezone=%s times=%s complexes=%s",
        settings.scheduler_timezone,
        settings.scheduler_times_csv,
        settings.scheduler_complex_nos_csv,
    )
    scheduler = CrawlScheduler(settings=settings)
    await scheduler.run()


def main() -> None:
    asyncio.run(run_scheduler_worker())


if __name__ == "__main__":
    main()
