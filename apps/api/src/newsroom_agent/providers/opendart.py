"""Opt-in OpenDART transport. Not yet wired to participant API routes."""

import asyncio
import json
import logging
import math
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import httpx

from newsroom_agent.providers.opendart_financials import (
    ANNUAL_REPORT_CODE,
    SAMSUNG_CORP_CODE,
    OpenDartError,
    RevenuePair,
    normalize_revenue,
)

_sensitive_request: ContextVar[bool] = ContextVar("opendart_sensitive_request", default=False)


class _TransportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # OpenDART requires a query-string key. Do not log URLs or reflected headers in this task.
        return not _sensitive_request.get()


_transport_log_filter = _TransportLogFilter()
for _logger_name in (
    "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_transport_log_filter)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError()


class OpenDartClient:
    base_url = "https://opendart.fss.or.kr/api"

    def __init__(
        self, api_key: str, transport: httpx.AsyncBaseTransport | None = None, *,
        enabled: bool = False, timeout_seconds: float = 20,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._api_key = api_key
        self._transport = transport
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._clock = clock

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._enabled is not True:
            raise OpenDartError("disabled")
        if (
            not isinstance(self._api_key, str) or not self._api_key.strip()
            or isinstance(self._timeout, bool) or not isinstance(self._timeout, (int, float))
            or not math.isfinite(self._timeout) or not 1 <= self._timeout <= 60
        ):
            raise OpenDartError("configuration")
        token = _sensitive_request.set(True)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, trust_env=False,
                transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
            ) as client:
                yield client
        except OpenDartError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise OpenDartError("timeout") from None
        except Exception:
            # Exception strings/URLs and raw provider messages may contain credentials.
            raise OpenDartError("unavailable") from None
        finally:
            _sensitive_request.reset(token)

    async def _request_json(self, client: httpx.AsyncClient, endpoint: str, params: dict) -> dict:
        async with asyncio.timeout(self._timeout):
            async with client.stream(
                "GET", f"{self.base_url}/{endpoint}",
                params={**params, "crtfc_key": self._api_key},
            ) as response:
                if response.status_code != 200:
                    code = {
                        400: "invalid_request", 401: "authentication", 403: "authentication",
                        408: "timeout", 429: "rate_limited", 504: "timeout",
                    }.get(response.status_code, "unavailable")
                    raise OpenDartError(code)
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise OpenDartError("invalid_response")
        try:
            payload = json.loads(
                body, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
            )
        except (ValueError, RecursionError):
            raise OpenDartError("invalid_response") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise OpenDartError("invalid_response")
        status = payload["status"]
        if not re.fullmatch(r"[0-9]{3}", status):
            raise OpenDartError("invalid_response")
        if status != "000":
            code = {
                "010": "authentication", "011": "authentication", "012": "authentication",
                "901": "authentication", "013": "no_data", "014": "no_data",
                "020": "rate_limited", "100": "invalid_request", "101": "invalid_request",
            }.get(status, "unavailable")
            raise OpenDartError(code)
        return payload

    async def fetch_revenue(self, start_year: int, end_year: int) -> RevenuePair:
        """At most two requests; fail the whole pair on missing/ambiguous/invalid data."""
        if (
            type(start_year) is not int or type(end_year) is not int
            or not 2015 <= start_year < end_year < self._clock().year
        ):
            raise OpenDartError("invalid_request")
        observations = []
        async with self._session() as client:
            for year in (start_year, end_year):
                payload = await self._request_json(client, "fnlttSinglAcntAll.json", {
                    "corp_code": SAMSUNG_CORP_CODE, "bsns_year": str(year),
                    "reprt_code": ANNUAL_REPORT_CODE, "fs_div": "CFS",
                })
                observations.append(normalize_revenue(payload, year, self._clock()))
        return RevenuePair(start=observations[0], end=observations[1])

    async def company(self, corp_code: str) -> dict[str, Any]:
        """Preserve the unused company-info scaffold with the same safe transport boundary."""
        if not isinstance(corp_code, str) or not re.fullmatch(r"[0-9]{8}", corp_code):
            raise OpenDartError("invalid_request")
        async with self._session() as client:
            return await self._request_json(client, "company.json", {"corp_code": corp_code})
