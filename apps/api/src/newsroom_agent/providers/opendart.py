from typing import Any

import httpx


class OpenDartClient:
    base_url = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise ValueError("OPENDART_API_KEY is required for live calls")
        self._api_key = api_key
        self._transport = transport

    async def company(self, corp_code: str) -> dict[str, Any]:
        params = {"crtfc_key": self._api_key, "corp_code": corp_code}
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
            response = await client.get(f"{self.base_url}/company.json", params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "000":
            raise RuntimeError(f"OpenDART error: {payload.get('status')} {payload.get('message')}")
        return payload
