"""HTTP correlation and bounded metadata only; never serialize requests or exceptions."""

import asyncio
import json
import logging
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger("newsroom_agent.requests")
ROUTES = frozenset({"/", "/health", "/api/v1/access", "/api/v1/plan", "/api/v1/execute",
                    "/api/v1/event/catalog", "/api/v1/event/plan", "/api/v1/event/execute",
                    "/api/v1/event/general", "/api/v1/research/plan", "/api/v1/research/execute",
                    "/api/v1/analyze", "/api/v1/operations", "/docs", "/redoc", "/openapi.json"})
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
ERROR_CODES = frozenset({
    "invalid_request", "invalid_conditions", "invalid_mock_data", "invalid_live_data",
    "invalid_snapshot_data", "invalid_planner_output", "planner_unavailable", "planner_disabled",
    "planner_configuration_error", "planner_timeout", "planner_rate_limited", "live_disabled",
    "public_data_rate_limited", "public_data_busy", "snapshot_disabled", "snapshot_changed",
    "snapshot_unavailable", "workshop_access_required", "workshop_access_unavailable",
    "internal_error", "research_timeout",
} | {f"{source}_{code}" for source in ("opendart", "kosis") for code in (
    "disabled", "configuration", "invalid_request", "authentication", "rate_limited", "no_data",
    "missing_account", "ambiguous_account", "missing_value", "invalid_amount",
    "unsupported_currency", "invalid_response", "timeout", "unavailable", "unsupported_conditions",
    "unsupported_period", "invalid_timestamp", "unsupported_unit", "incomplete_series",
    "duplicate_value", "invalid_value",
)})


@dataclass
class RequestContext:
    request_id: str
    error_code: str | None = None


_context: ContextVar[RequestContext | None] = ContextVar("http_request_context", default=None)


def request_id() -> str:
    context = _context.get()
    return context.request_id if context else str(uuid4())


def record_error(code: object) -> None:
    context = _context.get()
    if context is not None:
        context.error_code = code if isinstance(code, str) and code in ERROR_CODES else "http_error"


def configure_request_logging() -> None:
    # A dedicated stdout handler emits JSON without root logger formats or duplicate propagation.
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    # Uvicorn access messages include raw paths/queries. Also disabled in supported launch commands.
    logging.getLogger("uvicorn.access").disabled = True


def _route(path: str) -> str:
    return path if path in ROUTES else "/assets/*" if path.startswith("/assets/") else "other"


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp, allow_origins: list[str]) -> None:
        self.app = app
        self.allow_origins = allow_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        context = RequestContext(str(uuid4()))
        token = _context.set(context)
        started = perf_counter()
        status: int | None = None
        outcome = "completed"
        complete = False

        async def annotated_send(message: Message) -> None:
            nonlocal status, complete
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = context.request_id
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, receive, annotated_send)
            if not complete:
                outcome = "interrupted"
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            record_error("internal_error")
            if status is not None:
                outcome = "interrupted"
                # No original exception/context is handed to the server's traceback logger.
                raise RuntimeError("HTTP response interrupted") from None
            response = JSONResponse(status_code=500, content={"detail": {
                "code": "internal_error", "message": "요청을 처리하지 못했습니다. "
                "잠시 후 다시 시도하거나 문의용 요청 번호를 운영자에게 전달해 주세요.",
                "field_errors": {},
            }}, headers={"Cache-Control": "no-store", "Vary": "X-Workshop-Code"})
            origin = Headers(scope=scope).get("origin")
            if origin in self.allow_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
                response.headers.add_vary_header("Origin")
            await response(scope, receive, annotated_send)
        finally:
            try:
                error = context.error_code
                if outcome != "completed":
                    error = ("request_cancelled" if outcome == "cancelled"
                             else "response_interrupted")
                elif status is not None and status >= 400 and error is None:
                    error = {404: "not_found", 405: "method_not_allowed",
                             422: "invalid_request"}.get(status, "http_error")
                severity = "ERROR" if status is not None and status >= 500 else (
                    "WARNING" if error else "INFO"
                )
                LOGGER.log(getattr(logging, severity), json.dumps({
                    "timestamp": datetime.now(UTC).isoformat(), "severity": severity,
                    "event": "http_request", "request_id": context.request_id,
                    "method": scope["method"] if scope["method"] in METHODS else "OTHER",
                    "route": _route(scope["path"]), "status_code": status,
                    "duration_ms": round(max(0, perf_counter() - started) * 1000, 3),
                    "outcome": outcome, "error_code": error,
                }, separators=(",", ":")))
            finally:
                _context.reset(token)
