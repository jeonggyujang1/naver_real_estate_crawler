import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.settings import Settings


@dataclass(slots=True)
class NaverLandClient:
    settings: Settings

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
            "Referer": f"{self.settings.naver_land_base_url}/complexes/{complex_no}",
        }
        if self.settings.naver_land_authorization:
            headers["Authorization"] = self.settings.naver_land_authorization

        request = Request(url=url, headers=headers, method="GET")
        with urlopen(request, timeout=self.settings.crawler_timeout_seconds) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)

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
