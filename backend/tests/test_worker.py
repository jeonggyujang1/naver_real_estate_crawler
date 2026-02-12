import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import worker


def test_worker_main_runs_scheduler_once(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeScheduler:
        def __init__(self, settings):
            calls["settings"] = settings

        async def run(self):
            calls["ran"] = True

    monkeypatch.setattr(worker, "CrawlScheduler", FakeScheduler)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(
            scheduler_timezone="Asia/Seoul",
            scheduler_times_csv="09:00",
            scheduler_complex_nos_csv="2977",
        ),
    )

    worker.main()

    assert calls["ran"] is True
