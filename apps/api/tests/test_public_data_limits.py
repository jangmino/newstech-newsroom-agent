"""Deterministic time and offline transport; never load keys or use external APIs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import EmploymentQuery, KosisError
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import OpenDartError
from newsroom_agent.public_data_limits import PublicDataCallLimiter, PublicDataLimitError


def test_rolling_window_and_retry_after_use_request_start_times():
    seconds = 0
    limiter = PublicDataCallLimiter("kosis", 2, 1, timer=lambda: seconds)
    with limiter.slot():
        pass
    seconds = 30
    with limiter.slot():
        pass
    for timestamp, wait in ((30, 30), (59.2, 1)):
        seconds = timestamp
        with pytest.raises(PublicDataLimitError) as error, limiter.slot():
            pytest.fail("Exhausted window admitted a request")
        assert error.value.retry_after_seconds == wait
        assert error.value.code == "public_data_rate_limited"
    seconds = 60  # The first start expires exactly at the boundary; the second does not.
    with limiter.slot():
        pass
    with pytest.raises(PublicDataLimitError) as error, limiter.slot():
        pass
    assert error.value.retry_after_seconds == 30  # Rejections did not extend the window.


def test_concurrent_rejection_uses_no_quota_and_failure_releases_slot():
    limiter = PublicDataCallLimiter("opendart", 2, 1, timer=lambda: 0)
    with pytest.raises(RuntimeError), limiter.slot():
        for _ in range(3):
            with pytest.raises(PublicDataLimitError) as error, limiter.slot():
                pass
            assert error.value.code == "public_data_busy"
            assert error.value.source == "opendart"
            assert error.value.retry_after_seconds is None
        raise RuntimeError("offline failure")
    with limiter.slot():
        pass  # The failed attempt counts, but rejected attempts do not.
    with pytest.raises(PublicDataLimitError) as error, limiter.slot():
        pass
    assert error.value.code == "public_data_rate_limited"


def test_concurrency_admission_is_atomic_across_threads():
    limiter = PublicDataCallLimiter("kosis", 30, 2)
    barrier = Barrier(10)

    def attempt():
        try:
            with limiter.slot():
                barrier.wait(timeout=5)
                return "admitted"
        except PublicDataLimitError:
            barrier.wait(timeout=5)
            return "rejected"

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: attempt(), range(10)))
    assert results.count("admitted") == 2
    with limiter.slot():
        pass


@pytest.mark.parametrize("rpm,concurrent", [(0, 1), (301, 1), (True, 1), (1.5, 1),
                                            (1, 0), (1, 31), (1, False)])
def test_invalid_limits_are_rejected(rpm, concurrent):
    with pytest.raises(ValueError):
        PublicDataCallLimiter("kosis", rpm, concurrent)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["kosis", "opendart"])
@pytest.mark.parametrize("failure", ["cancel", "timeout"])
async def test_interrupted_transport_releases_slot_but_keeps_attempt_count(source, failure):
    limiter = PublicDataCallLimiter(source, 2, 1)
    started = asyncio.Event()
    calls = []

    async def transport(request):
        calls.append(request)
        if len(calls) == 1:
            started.set()
            if failure == "timeout":
                raise httpx.ReadTimeout("offline-key", request=request)
            await asyncio.Event().wait()
        return httpx.Response(503)

    if source == "kosis":
        client = KosisClient("offline-key", enabled=True, limiter=limiter,
                             transport=httpx.MockTransport(transport))

        async def fetch():
            return await client.fetch_employment(EmploymentQuery(
                entity="전국 시·도", metric="고용률", age_range="15-29세",
                start_year=2020, end_year=2024,
            ))
    else:
        client = OpenDartClient("offline-key", enabled=True, limiter=limiter,
                                transport=httpx.MockTransport(transport))

        async def fetch():
            return await client.fetch_revenue(2022, 2024)

    task = asyncio.create_task(fetch())
    await asyncio.wait_for(started.wait(), 2)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises((KosisError, OpenDartError)) as timed_out:
            await task
        assert timed_out.value.code == "timeout"
        assert "offline-key" not in str(timed_out.value)
    with pytest.raises((KosisError, OpenDartError)) as failure:
        await fetch()
    assert failure.value.code == "unavailable"  # A fresh HTTP attempt, not a leaked busy slot.
    with pytest.raises(PublicDataLimitError) as error:
        await fetch()
    assert error.value.code == "public_data_rate_limited"
    assert "offline-key" not in str(error.value)
    assert len(calls) == 2
