"""Streaming progress and exactly one terminal event, tied to the HTTP connection."""

import asyncio
import json
from collections.abc import Callable
from time import monotonic

from fastapi import HTTPException
from starlette.responses import StreamingResponse

from newsroom_agent.request_flow import FlowError, FlowState, flow
from newsroom_agent.request_logging import record_error, request_id


class EventAdmission:
    def __init__(self, maximum=40, total_seconds=180, wait_seconds=120):
        self.maximum = maximum
        self.total_seconds = total_seconds
        self.wait_seconds = wait_seconds
        self.active = 0
        self.provider_calls = {"gemini": 0, "opendart": 0, "kosis": 0}
        self.completed = 0
        self.failed = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def status(self):
        return {
            "active_requests": self.active,
            "max_requests": self.maximum,
            "wait_limit_seconds": self.wait_seconds,
            "request_limit_seconds": self.total_seconds,
            "scope": "single_process",
            "provider_calls": dict(self.provider_calls),
            "completed": self.completed, "failed": self.failed,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
        }

    def response(self, operation: Callable):
        if self.active >= self.maximum:
            raise HTTPException(
                429,
                detail={
                    "code": "queue_full",
                    "message": ("현재 실습 요청이 많아 접수하지 못했습니다. "
                        "입력은 유지됩니다. 잠시 후 다시 요청해 주세요."),
                    "field_errors": {},
                },
            )
        self.active += 1
        state = FlowState(wait_limit=self.wait_seconds, total_limit=self.total_seconds)
        correlation = request_id()

        async def run():
            token = flow.set(state)
            try:
                return await operation()
            finally:
                flow.reset(token)

        def event(kind, payload):
            return (
                json.dumps(
                    {"type": kind, "request_id": correlation, **payload},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )

        async def generate():
            task = asyncio.create_task(run())
            try:
                yield event("progress", state.progress())
                while not task.done():
                    remaining = self.total_seconds - (monotonic() - state.started)
                    if remaining <= 0:
                        raise TimeoutError
                    await asyncio.wait({task}, timeout=min(1, remaining))
                    if not task.done():
                        yield event("progress", state.progress())
                result = task.result()
                self.completed += 1
                yield event("result", {"result": result.model_dump(mode="json"),
                    "metrics": {"provider_calls": dict(state.calls),
                                "input_tokens": state.input_tokens,
                                "output_tokens": state.output_tokens, **state.progress()}})
            except TimeoutError:
                self.failed += 1
                record_error("request_timeout")
                yield event(
                    "error",
                    {
                        "detail": {
                            "code": "request_timeout",
                            "message": ("처리 시간이 길어 중단했습니다. "
                                "입력은 유지됩니다. "
                                "범위를 줄여 다시 승인하거나 공식 저장 자료를 선택해 주세요."),
                            "field_errors": {},
                        }
                    },
                )
            except HTTPException as exc:
                self.failed += 1
                record_error(exc.detail.get("code"))
                yield event("error", {"detail": exc.detail})
            except FlowError as exc:
                self.failed += 1
                record_error(exc.code)
                yield event(
                    "error",
                    {"detail": {"code": exc.code, "message": exc.message, "field_errors": {}}},
                )
            except Exception:
                self.failed += 1
                record_error("internal_error")
                yield event(
                    "error",
                    {
                        "detail": {
                            "code": "internal_error",
                            "message": ("요청을 완료하지 못했습니다. "
                                "입력은 유지됩니다. "
                                "문의용 요청 번호를 전달해 주세요."),
                            "field_errors": {},
                        }
                    },
                )
            finally:
                task.cancel()
                # Shield cleanup from the streaming response's disconnect cancellation scope.
                # Provider worker slots remain held until an already-sent synchronous call ends.
                cleanup = asyncio.create_task(self._finish(task, state))
                _cleanup_tasks.add(cleanup)
                cleanup.add_done_callback(_cleanup_tasks.discard)

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def _finish(self, task, state):
        try:
            await asyncio.gather(task, return_exceptions=True)
        finally:
            self.active -= 1
            for provider, count in state.calls.items():
                self.provider_calls[provider] += count
            self.input_tokens += state.input_tokens
            self.output_tokens += state.output_tokens


_cleanup_tasks: set[asyncio.Task] = set()
