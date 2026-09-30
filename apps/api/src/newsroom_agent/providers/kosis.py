"""Opt-in, single-request KOSIS transport for the approved employment contract."""

import asyncio
import json
import logging
import math
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime

import httpx

from newsroom_agent.providers.kosis_employment import (
    EmploymentQuery,
    EmploymentSeries,
    KosisError,
    normalize_employment,
)
from newsroom_agent.public_data_limits import PublicDataCallLimiter, PublicDataLimitError
from newsroom_agent.request_flow import FlowError, provider_slot, retry_delay, retry_public

_sensitive_request: ContextVar[bool] = ContextVar("kosis_sensitive_request", default=False)


class _TransportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # KOSIS uses query-string credentials. Suppress transport details in this task only.
        return not _sensitive_request.get()


_transport_log_filter = _TransportLogFilter()
for _logger_name in (
    "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_transport_log_filter)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError()


class KosisClient:
    data_url = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

    def __init__(
        self, api_key: str, transport: httpx.AsyncBaseTransport | None = None, *,
        enabled: bool = False, timeout_seconds: float = 20,
        clock: Callable[[], datetime] = _utc_now,
        limiter: PublicDataCallLimiter | None = None,
    ) -> None:
        self._api_key = api_key
        self._transport = transport
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._clock = clock
        self._limiter = limiter

    async def fetch_employment(self, query: EmploymentQuery) -> EmploymentSeries:
        if not isinstance(query, EmploymentQuery):
            raise KosisError("invalid_request")
        payload = await self.fetch_parameters(query.parameters)
        return normalize_employment(payload, query, self._clock())

    @retry_public("kosis")
    async def fetch_parameters(self, parameters: dict[str, str]) -> list:
        """Backend catalog supplies parameters; never an arbitrary HTTP proxy."""
        if self._enabled is not True:
            raise KosisError("disabled")
        if (
            not isinstance(self._api_key, str) or not self._api_key.strip()
            or isinstance(self._timeout, bool) or not isinstance(self._timeout, (int, float))
            or not math.isfinite(self._timeout) or not 1 <= self._timeout <= 60
        ):
            raise KosisError("configuration")
        token = _sensitive_request.set(True)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, trust_env=False,
                transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
            ) as client:
                async with provider_slot(self._limiter, "kosis"):
                    async with asyncio.timeout(self._timeout):
                        async with client.stream(
                            "GET", self.data_url,
                            params={**parameters, "apiKey": self._api_key},
                        ) as response:
                            if response.status_code != 200:
                                code = {
                                    400: "invalid_request", 401: "authentication",
                                    403: "authentication",
                                    408: "timeout", 429: "rate_limited", 504: "timeout",
                                }.get(response.status_code, "unavailable")
                                error = KosisError(code)
                                error.retry_after = retry_delay(response)
                                raise error
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=65_536):
                                body.extend(chunk)
                                if len(body) > 2_000_000:
                                    raise KosisError("invalid_response")
            try:
                payload = json.loads(
                    body, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                )
            except (ValueError, RecursionError):
                raise KosisError("invalid_response") from None
            if isinstance(payload, dict):
                # Accept documented integer or numeric-string error codes; never echo errMsg.
                err = payload.get("err")
                if type(err) not in (int, str) or str(err) not in {
                    "10", "11", "12", "20", "21", "30", "31", "40", "41", "42", "50",
                }:
                    raise KosisError("invalid_response")
                code = {
                    "10": "authentication", "11": "authentication", "12": "authentication",
                    "20": "invalid_request", "21": "invalid_request", "30": "no_data",
                    "31": "invalid_request", "40": "rate_limited", "41": "rate_limited",
                    "42": "authentication", "50": "unavailable",
                }[str(err)]
                raise KosisError(code)
            return payload
        except (FlowError, KosisError, PublicDataLimitError):
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise KosisError("timeout") from None
        except Exception:
            raise KosisError("unavailable") from None
        finally:
            _sensitive_request.reset(token)
