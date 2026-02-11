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

        referer = f"{self.settings.naver_land_base_url}/complexes/{complex_no}"
        headers = self._default_headers(referer=referer)
        return self._request_json(url=url, headers=headers)

    def search_complexes(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized_keyword = keyword.strip()
        if len(normalized_keyword) < 2:
            raise ValueError("keyword must be at least 2 characters")

        endpoint = f"{self.settings.naver_land_base_url}/api/search"
        url = f"{endpoint}?{urlencode({'keyword': normalized_keyword})}"
        headers = self._default_headers(referer=f"{self.settings.naver_land_base_url}/")
        payload = self._request_json(url=url, headers=headers)
        return self.summarize_search_complexes(payload, limit=limit)

    def _default_headers(self, referer: str) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer,
            "Origin": self.settings.naver_land_base_url,
        }
        if self.settings.naver_land_authorization:
            headers["Authorization"] = self.settings.naver_land_authorization
        if self.settings.naver_land_cookie:
            headers["Cookie"] = self.settings.naver_land_cookie
        return headers

    def _request_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
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
    def summarize_search_complexes(payload: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        if limit < 1:
            return []

        def _extract_from_node(node: Any) -> list[dict[str, Any]]:
            if isinstance(node, list):
                result: list[dict[str, Any]] = []
                for child in node:
                    result.extend(_extract_from_node(child))
                return result
            if isinstance(node, dict):
                current: list[dict[str, Any]] = []
                complex_no = node.get("complexNo") or node.get("complexNumber")
                complex_name = node.get("complexName") or node.get("name")
                if complex_no and complex_name:
                    current.append(node)

                for value in node.values():
                    current.extend(_extract_from_node(value))
                return current
            return []

        candidates = _extract_from_node(payload)

        normalized: list[dict[str, Any]] = []
        seen_complex_nos: set[int] = set()
        for item in candidates:
            complex_no = item.get("complexNo") or item.get("complexNumber")
            try:
                complex_no_int = int(complex_no)
            except (TypeError, ValueError):
                continue
            if complex_no_int in seen_complex_nos:
                continue
            complex_name = str(item.get("complexName") or item.get("name") or "").strip()
            if not complex_name:
                continue

            normalized_item = {
                "complex_no": complex_no_int,
                "complex_name": complex_name,
                "real_estate_type_name": item.get("realEstateTypeName") or item.get("realEstateType"),
                "sido_name": item.get("sidoName"),
                "gugun_name": item.get("gugunName"),
                "dong_name": item.get("dongName"),
            }
            normalized.append(normalized_item)
            seen_complex_nos.add(complex_no_int)
            if len(normalized) >= limit:
                break

        return normalized

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
