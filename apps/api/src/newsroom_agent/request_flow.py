"""Request-bound, bounded async admission. No persistent jobs or provider payload logging."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

from newsroom_agent.providers.planner import PlannerRateLimited
from newsroom_agent.public_data_limits import PublicDataLimitError


class FlowError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass
class FlowState:
    started: float = field(default_factory=monotonic)
    waited: float = 0
    wait_limit: float = 120
    total_limit: float = 180
    stage: str = "accepted"
    provider: str | None = None
    calls: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    waiting_queue: deque | None = field(default=None, repr=False)
    waiting_ticket: object | None = field(default=None, repr=False)

    def progress(self):
        ahead = None
        if self.waiting_queue is not None and self.waiting_ticket in self.waiting_queue:
            ahead = self.waiting_queue.index(self.waiting_ticket)
        return {
            "stage": self.stage,
            "provider": self.provider,
            "elapsed_seconds": round(monotonic() - self.started, 1),
            "waited_seconds": round(self.waited, 1),
            "queue_ahead": ahead,
            "wait_limit_seconds": self.wait_limit,
            "request_limit_seconds": self.total_limit,
        }


flow: ContextVar[FlowState | None] = ContextVar("event_flow", default=None)


def progress(stage: str, provider: str | None = None):
    state = flow.get()
    if state:
        state.stage, state.provider = stage, provider


@asynccontextmanager
async def provider_slot(limiter, provider: str):
    state = flow.get()
    if limiter is None:
        yield
        return
    if state is None:
        with limiter.slot():
            yield
        return
    # All queued admission runs on this process's ASGI event loop. Legacy slots still
    # share the limiter's locked counters; no second independent external-call budget.
    if not hasattr(limiter, "_event_waiters"):
        limiter._event_waiters = deque()
    queue = limiter._event_waiters
    ticket = object()
    queue.append(ticket)
    state.waiting_queue, state.waiting_ticket = queue, ticket
    entered = False
    slot = None
    progress("waiting", provider)
    try:
        while True:
            before = monotonic()
            if state.waited >= state.wait_limit:
                raise FlowError(
                    "queue_timeout",
                    ("요청 대기 시간이 길어 중단했습니다. "
                        "입력은 유지됩니다. "
                        "잠시 후 다시 요청하거나 공식 저장 자료를 선택해 주세요."),
                )
            if queue[0] is ticket and monotonic() >= getattr(limiter, "_event_pause_until", 0):
                slot = limiter.slot()
                try:
                    slot.__enter__()
                    entered = True
                except (PlannerRateLimited, PublicDataLimitError):
                    pass
                if entered:
                    queue.popleft()
                    state.waiting_queue, state.waiting_ticket = None, None
                    state.calls[provider] = state.calls.get(provider, 0) + 1
                    progress("running", provider)
                    break
            await asyncio.sleep(min(0.1, max(0.001, state.wait_limit - state.waited)))
            state.waited += monotonic() - before
        yield
    finally:
        if ticket in queue:
            queue.remove(ticket)
        state.waiting_queue, state.waiting_ticket = None, None
        if entered:
            slot.__exit__(None, None, None)


async def interpret(model, payload):
    if flow.get() is not None and hasattr(model, "interpret_queued"):
        return await model.interpret_queued(payload)
    return await asyncio.to_thread(model.interpret, payload)


def retry_delay(response) -> float | None:
    if flow.get() is None or response is None or response.status_code != 429:
        return None
    raw = response.headers.get("retry-after", "")
    # Only an explicit, bounded provider instruction. Never retry an ambiguous timeout.
    if raw.isdigit() and 1 <= int(raw) <= 30:
        return float(raw)
    return None


async def wait_retry(seconds: float, provider: str, limiter=None):
    state = flow.get()
    if state is None or state.waited + seconds > state.wait_limit:
        raise FlowError(
            "queue_timeout", "공급자 대기 시간이 길어 중단했습니다. "
            "잠시 후 다시 요청해 주세요."
        )
    if limiter is not None:
        limiter._event_pause_until = max(
            getattr(limiter, "_event_pause_until", 0), monotonic() + seconds
        )
    progress("retry_wait", provider)
    started = monotonic()
    try:
        await asyncio.sleep(seconds)
    finally:
        state.waited += monotonic() - started


def retry_public(provider):
    """Retry only an explicitly rate-rejected HTTP call, not a whole multi-call analysis."""
    from functools import wraps

    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            for attempt in range(2):
                try:
                    return await function(*args, **kwargs)
                except Exception as exc:
                    delay = getattr(exc, "retry_after", None)
                    if attempt or delay is None or flow.get() is None:
                        raise
                    await wait_retry(delay, provider, getattr(args[0], "_limiter", None))

        return wrapped

    return decorate
