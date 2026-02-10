import json
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.settings import Settings


@dataclass(slots=True)
class NaverLandClient:
    settings: Settings

    @staticmethod
    def _is_retryable_status(code: int) -> bool:
        return code == 429 or 500 <= code < 600

    @staticmethod
    def _is_retryable_api_code(code: str | None) -> bool:
        if not code:
            return False
        return code in {"TOO_MANY_REQUESTS", "TEMPORARY_ERROR", "INTERNAL_SERVER_ERROR"}

    @staticmethod
    def _sleep_seconds(attempt_index: int, retry_after_header: str | None = None) -> float:
        if retry_after_header and retry_after_header.isdigit():
            return float(retry_after_header)
        # Exponential backoff + jitter to reduce burst retries.
        return min(8.0, (0.6 * (2**attempt_index)) + random.uniform(0.0, 0.3))

    def fetch_complex_articles(
        self,
        complex_no: int,
        page: int = 1,
        real_estate_type: str = "APT:ABYG:JGC",
        trade_type: str = "A1:B1:B2",
    ) -> dict[str, Any]:
        endpoint = f"{self.settings.naver_land_base_url}/api/articles/complex/{complex_no}"
        params = {
            "complexNo": complex_no,
            "page": page,
            "realEstateType": real_estate_type,
            "tradeType": trade_type,
            "tag": "::::::::",
            "rentPriceMin": "0",
            "rentPriceMax": "900000000",
            "priceMin": "0",
            "priceMax": "900000000",
            "areaMin": "0",
            "areaMax": "900000000",
            "oldBuildYears": "",
            "recentlyBuildYears": "",
            "minHouseHoldCount": "",
            "maxHouseHoldCount": "",
            "showArticle": "false",
            "sameAddressGroup": "false",
            "minMaintenanceCost": "",
            "maxMaintenanceCost": "",
            "priceType": "RETAIL",
            "directions": "",
            "buildingNos": "",
            "areaNos": "",
            "type": "list",
            "order": "rank",
        }
        url = f"{endpoint}?{urlencode(params)}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.settings.naver_land_base_url}/complexes/{complex_no}",
            "Origin": self.settings.naver_land_base_url,
        }
        if self.settings.naver_land_authorization:
            headers["Authorization"] = self.settings.naver_land_authorization

        max_attempts = max(1, self.settings.crawler_max_retry)

        for attempt_index in range(max_attempts):
            request = Request(url=url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=self.settings.crawler_timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                payload = json.loads(raw)

                if payload.get("success") is False:
                    code = payload.get("code")
                    message = payload.get("message") or "Unknown error"
                    if attempt_index < max_attempts - 1 and self._is_retryable_api_code(code):
                        time.sleep(self._sleep_seconds(attempt_index))
                        continue
                    raise RuntimeError(f"Naver API returned error. code={code}, message={message}")
                return payload
            except HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if attempt_index < max_attempts - 1 and self._is_retryable_status(exc.code):
                    time.sleep(self._sleep_seconds(attempt_index, retry_after_header=retry_after))
                    continue
                raise RuntimeError(f"Naver API HTTP error: {exc.code} {exc.reason}") from exc
            except URLError as exc:
                if attempt_index < max_attempts - 1:
                    time.sleep(self._sleep_seconds(attempt_index))
                    continue
                raise RuntimeError(f"Naver API network error: {exc.reason}") from exc
            except TimeoutError as exc:
                if attempt_index < max_attempts - 1:
                    time.sleep(self._sleep_seconds(attempt_index))
                    continue
                raise RuntimeError("Naver API request timed out") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError("Naver API returned invalid JSON") from exc

        raise RuntimeError("Naver API request failed after retries")

    @staticmethod
    def summarize_articles(payload: dict[str, Any]) -> list[dict[str, Any]]:
        articles = payload.get("articleList", [])
        summary: list[dict[str, Any]] = []
        for item in articles:
            summary.append(
                {
                    "article_no": item.get("articleNo"),
                    "article_name": item.get("articleName"),
                    "trade_type": item.get("tradeTypeName"),
                    "price": item.get("dealOrWarrantPrc"),
                    "rent_price": item.get("rentPrc"),
                    "floor_info": item.get("floorInfo"),
                    "area_m2": item.get("area1"),
                    "direction": item.get("direction"),
                    "confirmed_at": item.get("articleConfirmYmd"),
                }
            )
        return summary
