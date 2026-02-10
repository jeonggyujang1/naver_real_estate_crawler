import io
import pathlib
import sys
from urllib.error import HTTPError

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

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
