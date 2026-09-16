"""Clock- and event-driven cache tests; no credentials, external calls, or timed sleeps."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from newsroom_agent.public_data_cache import PublicDataCache

KEY = (("contract", "test-v1"), ("period", "2020-2024"))
OTHER = (("contract", "test-v1"), ("period", "2021-2024"))


class Clock:
    seconds = 0.0
    wall_shift = 0.0

    def timer(self):
        return self.seconds

    def now(self):
        return datetime(2026, 9, 16, tzinfo=UTC) + timedelta(
            seconds=self.seconds + self.wall_shift,
        )


def cache(clock, max_entries=2):
    return PublicDataCache(ttl_seconds=10, max_entries=max_entries,
                           timer=clock.timer, clock=clock.now)


@pytest.mark.asyncio
async def test_reuse_preserves_original_time_and_isolates_mutations():
    clock = Clock()
    store = cache(clock)
    calls = 0
    original = {"value": ["40.8"], "retrieved_at": "2026-09-15T23:59:59Z"}

    async def fetch():
        nonlocal calls
        calls += 1
        clock.seconds += 4  # TTL starts after the entire fetch, not at its start.
        return original

    first, miss = await store.get(KEY, fetch)
    first["value"][0] = "bad"
    original["value"][0] = "also bad"
    clock.seconds = 13.9
    second, hit = await store.get(KEY, fetch)
    assert second == {"value": ["40.8"], "retrieved_at": "2026-09-15T23:59:59Z"}
    assert calls == 1 and miss.status == "miss" and hit.status == "hit"
    assert miss.stored_at == hit.stored_at == "2026-09-16T00:00:04+00:00"
    assert miss.expires_at == hit.expires_at == "2026-09-16T00:00:14+00:00"
    assert hit.age_seconds == pytest.approx(9.9) and hit.scope == "process"
    clock.seconds = 14  # Exact expiry: a hit did not extend the deadline.
    _, fresh = await store.get(KEY, fetch)
    assert calls == 2 and fresh.status == "miss"
    assert fresh.stored_at != hit.stored_at
    await store.close()


@pytest.mark.asyncio
async def test_wall_clock_changes_do_not_change_ttl():
    clock = Clock()
    store = cache(clock)

    async def fetch():
        return "data"

    _, first = await store.get(KEY, fetch)
    clock.wall_shift = 86_400
    clock.seconds = 9
    _, hit = await store.get(KEY, fetch)
    assert hit.status == "hit" and hit.age_seconds == 9
    assert hit.expires_at == first.expires_at
    clock.wall_shift = -86_400
    clock.seconds = 10
    assert (await store.get(KEY, fetch))[1].status == "miss"
    await store.close()


@pytest.mark.asyncio
async def test_lru_bound_and_expired_entry_removal():
    clock = Clock()
    store = cache(clock)
    third = (("contract", "third"),)
    calls = []

    async def read(key):
        async def fetch():
            calls.append(key)
            return key
        return (await store.get(key, fetch))[1].status

    assert await read(KEY) == await read(OTHER) == "miss"
    assert await read(KEY) == "hit"  # OTHER becomes the least recently used entry.
    assert await read(third) == "miss"
    assert await read(KEY) == "hit"
    assert await read(OTHER) == "miss"
    clock.seconds = 10
    assert await read(KEY) == "miss"
    assert len(store._entries) == 1
    assert len(calls) == 5
    await store.close()


@pytest.mark.asyncio
async def test_thirty_identical_requests_share_one_fetch():
    store = cache(Clock())
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"value": "verified"}

    requests = [asyncio.create_task(store.get(KEY, fetch)) for _ in range(30)]
    await started.wait()
    release.set()
    results = await asyncio.gather(*requests)
    assert calls == 1
    assert [meta.status for _, meta in results].count("miss") == 1
    assert [meta.status for _, meta in results].count("coalesced") == 29
    results[0][0]["value"] = "changed"
    assert results[-1][0]["value"] == "verified"
    assert (await store.get(KEY, fetch))[1].status == "hit"
    await store.close()


@pytest.mark.asyncio
async def test_different_keys_run_independently():
    store = cache(Clock())
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        if calls == 2:
            started.set()
        await release.wait()
        return "data"

    requests = [asyncio.create_task(store.get(key, fetch)) for key in (KEY, OTHER)]
    await asyncio.wait_for(started.wait(), 1)
    release.set()
    assert all(meta.status == "miss" for _, meta in await asyncio.gather(*requests))
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [True, False])
async def test_cancelled_waiter_cannot_cancel_another_approved_request(cancel_first):
    store = cache(Clock())
    started, release = asyncio.Event(), asyncio.Event()
    cancelled = False

    async def fetch():
        nonlocal cancelled
        started.set()
        try:
            await release.wait()
            return "data"
        except asyncio.CancelledError:
            cancelled = True
            raise

    requests = [asyncio.create_task(store.get(KEY, fetch)) for _ in range(2)]
    await started.wait()
    index = 0 if cancel_first else 1
    requests[index].cancel()
    with pytest.raises(asyncio.CancelledError):
        await requests[index]
    release.set()
    value, meta = await requests[1 - index]
    assert value == "data" and not cancelled
    assert meta.status == ("coalesced" if cancel_first else "miss")
    assert (await store.get(KEY, fetch))[1].status == "hit"
    await store.close()


@pytest.mark.asyncio
async def test_shared_failure_is_not_cached_and_next_approval_can_retry():
    store = cache(Clock())
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        if calls == 1:
            raise ValueError("failed normalization")
        return "complete data"

    requests = [asyncio.create_task(store.get(KEY, fetch)) for _ in range(3)]
    await started.wait()
    release.set()
    failures = await asyncio.gather(*requests, return_exceptions=True)
    assert all(isinstance(failure, ValueError) for failure in failures)
    assert calls == 1
    value, meta = await store.get(KEY, fetch)
    assert calls == 2 and value == "complete data" and meta.status == "miss"
    await store.close()


@pytest.mark.asyncio
async def test_expired_value_is_never_returned_when_refresh_fails():
    clock = Clock()
    store = cache(clock)

    async def success():
        return "old data"

    async def failure():
        raise ValueError("no new data")

    await store.get(KEY, success)
    clock.seconds = 10
    with pytest.raises(ValueError, match="no new data"):
        await store.get(KEY, failure)
    assert not store._entries and not store._inflight
    assert (await store.get(KEY, success))[1].status == "miss"
    await store.close()


@pytest.mark.asyncio
async def test_shutdown_cancels_outstanding_fetch_and_discards_values():
    store = cache(Clock())
    started, stopped = asyncio.Event(), asyncio.Event()

    async def fetch():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    request = asyncio.create_task(store.get(KEY, fetch))
    await started.wait()
    await store.close()
    assert stopped.is_set()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not store._entries and not store._inflight
    with pytest.raises(RuntimeError, match="closed"):
        await store.get(KEY, fetch)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [True, False])
async def test_all_waiters_cancelled_still_cleanup_without_unobserved_failure(fails):
    store = cache(Clock())
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        started.set()
        await release.wait()
        if fails:
            raise ValueError("safe failure")
        return "data"

    request = asyncio.create_task(store.get(KEY, fetch))
    await started.wait()
    task = store._inflight[KEY]
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    release.set()
    # Await the done callback, not the task: failures must be consumed by the cache itself.
    done = asyncio.Event()
    task.add_done_callback(lambda _: done.set())
    await done.wait()
    assert not store._inflight
    assert len(store._entries) == (0 if fails else 1)
    assert not task._log_traceback
    await store.close()


@pytest.mark.parametrize("options", [
    {"ttl_seconds": 0}, {"ttl_seconds": True}, {"ttl_seconds": 86401},
    {"max_entries": 0}, {"max_entries": 257}, {"max_entries": 1.5},
])
def test_invalid_cache_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        PublicDataCache(**options)
