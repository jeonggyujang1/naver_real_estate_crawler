import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import main


def test_crawler_ingest_maps_rate_limit_error_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_ingest(**_kwargs):
        raise RuntimeError("Naver API HTTP error: 429 Too Many Requests")

    monkeypatch.setattr(main, "ingest_complex_snapshot", fake_ingest)

    with pytest.raises(HTTPException) as exc_info:
        main.crawler_ingest(complex_no=2977, page=1, max_pages=1, db=object())

    assert exc_info.value.status_code == 503
    assert "잠시 후" in str(exc_info.value.detail)


def test_crawler_ingest_maps_upstream_error_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_ingest(**_kwargs):
        raise RuntimeError("Naver API HTTP error: 403 Forbidden")

    monkeypatch.setattr(main, "ingest_complex_snapshot", fake_ingest)

    with pytest.raises(HTTPException) as exc_info:
        main.crawler_ingest(complex_no=2977, page=1, max_pages=1, db=object())

    assert exc_info.value.status_code == 502
    assert "네이버 부동산 응답 오류" in str(exc_info.value.detail)


def test_crawler_search_complexes_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def search_complexes(self, keyword: str, limit: int):
            assert keyword == "래미안"
            assert limit == 5
            return [
                {
                    "complex_no": 2977,
                    "complex_name": "래미안 대치 팰리스",
                    "sido_name": "서울시",
                }
            ]

    monkeypatch.setattr(main, "NaverLandClient", FakeClient)

    result = main.crawler_search_complexes(keyword="래미안", limit=5)

    assert result["keyword"] == "래미안"
    assert result["count"] == 1
    assert result["items"][0]["complex_no"] == 2977


def test_crawler_search_complexes_maps_rate_limit_error_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def search_complexes(self, keyword: str, limit: int):
            raise RuntimeError("Naver API HTTP error: 429 Too Many Requests")

    monkeypatch.setattr(main, "NaverLandClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        main.crawler_search_complexes(keyword="래미안", limit=10)

    assert exc_info.value.status_code == 503
    assert "잠시 후" in str(exc_info.value.detail)


def test_registration_rate_limit_blocks_excessive_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "auth_register_rate_limit_per_window", 2)
    monkeypatch.setattr(main.settings, "auth_register_rate_limit_window_minutes", 60)
    main.REGISTER_ATTEMPTS.clear()

    main._enforce_registration_rate_limit("test-ip")
    main._enforce_registration_rate_limit("test-ip")

    with pytest.raises(HTTPException) as exc_info:
        main._enforce_registration_rate_limit("test-ip")

    assert exc_info.value.status_code == 429
    assert "회원가입 요청이 너무 많습니다" in str(exc_info.value.detail)


def test_parse_scheduler_times_normalizes_values() -> None:
    parsed = main._parse_scheduler_times("18:00, 09:00,wrong,25:00,09:00")
    assert parsed == ["09:00", "18:00"]
