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
