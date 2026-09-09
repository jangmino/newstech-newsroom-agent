from typing import Any

import httpx


class KosisClient:
    search_url = "https://kosis.kr/openapi/statisticsSearch.do"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("KOSIS_API_KEY is required for live calls")
        self._api_key = api_key
        self._transport = transport

    async def search(self, query: str, result_count: int = 20) -> list[dict[str, Any]]:
        params = {
            "method": "getList",
            "apiKey": self._api_key,
            "searchNm": query,
            "format": "json",
            "jsonVD": "Y",
            "startCount": "1",
            "resultCount": str(result_count),
        }
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
            response = await client.get(self.search_url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected KOSIS response shape")
        return payload
