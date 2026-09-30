"""Bounded, event-loop-local storage of normalized public data, never whole responses."""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal

from newsroom_agent.models import CacheMetadata
from newsroom_agent.request_flow import flow, progress

CacheKey = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Entry[T]:
    value: T
    completed: float
    stored_at: datetime


class PublicDataCache[T]:
    """One instance per provider in one ASGI lifespan; no files or credential access."""

    def __init__(
        self, ttl_seconds: int = 3600, max_entries: int = 64, *,
        timer: Callable[[], float] = monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Invalid public data cache TTL")
        if type(max_entries) is not int or not 1 <= max_entries <= 256:
            raise ValueError("Invalid public data cache size")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._timer = timer
        self._clock = clock
        self._entries: OrderedDict[CacheKey, _Entry[T]] = OrderedDict()
        self._inflight: dict[CacheKey, asyncio.Task[_Entry[T]]] = {}
        self._closed = False
        self._waiters: dict[asyncio.Task, int] = {}

    async def get(
        self, key: CacheKey, loader: Callable[[], Awaitable[T]],
    ) -> tuple[T, CacheMetadata]:
        if self._closed:
            raise RuntimeError("Public data cache is closed")
        # No await in lookup/insertion: requests on this event loop cannot race here.
        self._prune()
        entry = self._entries.get(key)
        status: Literal["miss", "hit", "coalesced"]
        if entry is not None:
            self._entries.move_to_end(key)
            status = "hit"
        else:
            task = self._inflight.get(key)
            if task is not None and task.cancelling():
                task = None
            status = "coalesced" if task is not None else "miss"
            if task is None:
                task = asyncio.create_task(self._load(key, loader), name="public-data-fetch")
                self._inflight[key] = task  # Keep a strong reference through completion.
                task.add_done_callback(self._consume_exception)
            # A disconnected waiter must not cancel the fetch used by other approved requests.
            self._waiters[task] = self._waiters.get(task, 0) + 1
            managed = flow.get() is not None
            if managed:
                progress("source_wait")
            try:
                entry = await asyncio.shield(task)
            finally:
                self._waiters[task] -= 1
                if self._waiters[task] == 0:
                    del self._waiters[task]
                    if managed and not task.done():
                        task.cancel()
        return deepcopy(entry.value), CacheMetadata(
            status=status, stored_at=entry.stored_at.isoformat(),
            expires_at=(entry.stored_at + timedelta(seconds=self._ttl)).isoformat(),
            ttl_seconds=self._ttl, age_seconds=max(0, self._timer() - entry.completed),
        )

    async def _load(self, key: CacheKey, loader: Callable[[], Awaitable[T]]) -> _Entry[T]:
        try:
            value = await loader()  # Complete provider normalization before storing anything.
            entry = _Entry(deepcopy(value), self._timer(), self._clock())
            if not self._closed:
                self._prune()
                self._entries[key] = entry
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            return entry
        finally:
            if self._inflight.get(key) is asyncio.current_task():
                self._inflight.pop(key, None)

    def _prune(self) -> None:
        now = self._timer()
        for key, entry in list(self._entries.items()):
            if now - entry.completed >= self._ttl:
                del self._entries[key]

    @staticmethod
    def _consume_exception(task: asyncio.Task) -> None:
        # All waiters may have left; consume failure without logging provider details.
        if not task.cancelled():
            task.exception()

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._entries.clear()
