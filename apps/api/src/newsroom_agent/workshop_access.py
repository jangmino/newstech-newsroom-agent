"""Shared event access, checked before routing or reading a request body."""

import hashlib
import re
import secrets
from collections.abc import Callable

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from newsroom_agent.config import Settings
from newsroom_agent.models import WorkshopAccessStatus


def access_status(settings: Settings) -> WorkshopAccessStatus:
    code = settings.workshop_access_code
    required = bool(code) or settings.app_env not in {"local", "test"}
    available = not required or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", code) is not None
    return WorkshopAccessStatus(required=required, available=available)


class WorkshopAccessMiddleware:
    def __init__(self, app: ASGIApp, settings: Callable[[], Settings]) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        protected = (path == "/api" or path.startswith("/api/") or path in
                     {"/docs", "/redoc", "/openapi.json"} or path.startswith("/docs/"))
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers.add_vary_header("X-Workshop-Code")
            await send(message)

        settings = self.settings()
        status = access_status(settings)
        public_status = path == "/api/v1/access" and scope["method"] == "GET"
        if not public_status:
            failure = None
            if not status.available:
                failure = (503, "workshop_access_unavailable",
                           "행사 입장 설정을 확인하고 있습니다. 운영자에게 문의해 주세요.")
            elif status.required:
                codes = [value for name, value in scope["headers"]
                         if name.lower() == b"x-workshop-code"]
                supplied = codes[0] if len(codes) == 1 else b""
                if (not re.fullmatch(rb"[A-Za-z0-9_-]{16,128}", supplied)
                    or not secrets.compare_digest(
                        hashlib.sha256(supplied).digest(),
                        hashlib.sha256(settings.workshop_access_code.encode()).digest(),
                    )):
                    failure = (401, "workshop_access_required",
                               "행사 접근코드를 확인해 주세요. "
                               "운영자가 안내한 코드로 다시 입장해 주세요.")
            if failure:
                status_code, code, message = failure
                response = JSONResponse(status_code=status_code, content={"detail": {
                    "code": code, "message": message, "field_errors": {},
                }}, headers={"WWW-Authenticate": "Workshop"} if status_code == 401 else None)
                await response(scope, receive, no_store)
                return
        await self.app(scope, receive, no_store)
