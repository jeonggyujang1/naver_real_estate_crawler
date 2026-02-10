import io
import pathlib
import sys
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.crawler import naver_client
from app.settings import Settings


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_fetch_complex_articles_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(crawler_max_retry=2, crawler_timeout_seconds=1.0)
    client = naver_client.NaverLandClient(settings=settings)

    calls = {"count": 0}

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                url="https://new.land.naver.com/api/articles/complex/1",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b'{"success":false,"message":"Rate limit exceeded"}'),
            )
        return _FakeResponse(b'{"success":true,"articleList":[{"articleNo":"1"}]}')

    monkeypatch.setattr(naver_client, "urlopen", fake_urlopen)

    payload = client.fetch_complex_articles(complex_no=1, page=1)
    assert payload["success"] is True
    assert len(payload["articleList"]) == 1
    assert calls["count"] == 2


def test_fetch_complex_articles_raises_when_api_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(crawler_max_retry=1, crawler_timeout_seconds=1.0)
    client = naver_client.NaverLandClient(settings=settings)

    def fake_urlopen(_request, timeout):
        return _FakeResponse(b'{"success":false,"code":"TOO_MANY_REQUESTS","message":"Rate limit exceeded"}')

    monkeypatch.setattr(naver_client, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError):
        client.fetch_complex_articles(complex_no=2977, page=1)


def test_search_complexes_retries_on_429_and_returns_normalized_items(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(crawler_max_retry=2, crawler_timeout_seconds=1.0)
    client = naver_client.NaverLandClient(settings=settings)

    calls = {"count": 0}

    def fake_urlopen(_request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                url="https://new.land.naver.com/api/search?keyword=래미안",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b'{"success":false,"message":"Rate limit exceeded"}'),
            )
        return _FakeResponse(
            (
                '{"success":true,"complexList":[{"complexNo":"2977","complexName":"래미안 대치 팰리스",'
                '"sidoName":"서울시","gugunName":"강남구","dongName":"대치동"},'
                '{"complexNo":"2977","complexName":"중복 제거"}]}'
            ).encode("utf-8")
        )

    monkeypatch.setattr(naver_client, "urlopen", fake_urlopen)

    items = client.search_complexes(keyword="래미안", limit=10)
    assert calls["count"] == 2
    assert len(items) == 1
    assert items[0]["complex_no"] == 2977
    assert items[0]["complex_name"] == "래미안 대치 팰리스"
    assert items[0]["gugun_name"] == "강남구"


def test_summarize_search_complexes_handles_nested_payload_shape() -> None:
    payload = {
        "success": True,
        "result": {
            "complexes": [
                {"complexNumber": 111, "name": "한강자이", "sidoName": "서울시"},
                {"complexNo": "222", "complexName": "래미안 원베일리", "dongName": "반포동"},
            ]
        },
    }

    items = naver_client.NaverLandClient.summarize_search_complexes(payload=payload, limit=10)
    assert len(items) == 2
    assert items[0]["complex_no"] == 111
    assert items[0]["complex_name"] == "한강자이"
    assert items[1]["complex_no"] == 222
    assert items[1]["complex_name"] == "래미안 원베일리"
