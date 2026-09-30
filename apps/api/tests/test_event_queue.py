"""Offline concurrent admission, disconnect ownership, progress and secret-safe failures."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.genai import errors

from newsroom_agent import main
from newsroom_agent.event_service import load_snapshots
from newsroom_agent.event_stream import EventAdmission
from newsroom_agent.providers.gemini_planner import GeminiCallLimiter, GeminiQuestionPlanner
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.planner import (
    PlannerAuthenticationError,
    PlannerBillingError,
    PlannerRateLimited,
    PlannerUnavailable,
)
from newsroom_agent.public_data_cache import PublicDataCache
from newsroom_agent.public_data_limits import PublicDataCallLimiter
from newsroom_agent.request_flow import FlowError, FlowState, flow, provider_slot


@pytest.mark.asyncio
async def test_thirty_concurrent_wait_fifo_and_respect_active_limit():
    limiter = GeminiCallLimiter(100, 2)
    order, peak = [], 0

    async def job(i):
        nonlocal peak
        token = flow.set(FlowState())
        try:
            async with provider_slot(limiter, "gemini"):
                order.append(i)
                peak = max(peak, limiter.active)
                await asyncio.sleep(0.001)
        finally:
            flow.reset(token)

    await asyncio.gather(*(job(i) for i in range(30)))
    assert order == list(range(30))
    assert peak == 2 and limiter.active == 0 and len(limiter.calls) == 30


@pytest.mark.asyncio
async def test_minute_budget_waits_until_old_calls_expire():
    now = [0.0]
    limiter = GeminiCallLimiter(1, 1, clock=lambda: now[0])
    with limiter.slot():
        pass
    token = flow.set(FlowState())

    async def enter():
        async with provider_slot(limiter, "gemini"):
            return True

    task = asyncio.create_task(enter())
    await asyncio.sleep(0.02)
    assert not task.done()
    now[0] = 61
    assert await asyncio.wait_for(task, 1)
    flow.reset(token)


@pytest.mark.asyncio
async def test_wait_timeout_and_cancel_remove_ticket_without_external_call():
    limiter = PublicDataCallLimiter("kosis", 30, 1)
    token = flow.set(FlowState(wait_limit=0.03))
    with limiter.slot():
        with pytest.raises(FlowError, match="대기"):
            async with provider_slot(limiter, "kosis"):
                pytest.fail("must not run")
    assert not limiter._event_waiters and len(limiter._starts) == 1
    flow.reset(token)
    token = flow.set(FlowState())

    async def wait():
        async with provider_slot(limiter, "kosis"):
            pytest.fail("must not run")

    with limiter.slot():
        task = asyncio.create_task(wait())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not limiter._event_waiters
    flow.reset(token)


@pytest.mark.asyncio
async def test_legacy_non_event_calls_still_fail_fast():
    limiter = GeminiCallLimiter(1, 1)
    with limiter.slot():
        with pytest.raises(PlannerRateLimited):
            async with provider_slot(limiter, "gemini"):
                pass


@pytest.mark.asyncio
async def test_shared_fetch_survives_one_cancel_and_stops_after_last_cancel():
    cache = PublicDataCache()
    entered, stop, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def loader():
        entered.set()
        try:
            await stop.wait()
            return "official"
        finally:
            cancelled.set()

    token = flow.set(FlowState())
    first = asyncio.create_task(cache.get(("same",), loader))
    await entered.wait()
    second = asyncio.create_task(cache.get(("same",), loader))
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert not cancelled.is_set()
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    await asyncio.wait_for(cancelled.wait(), 1)
    assert not cache._waiters
    await cache.close()
    flow.reset(token)


def fake_model(status):
    @contextmanager
    def client():
        def generate_content(**kwargs):
            raise errors.APIError(status, {"error": {"message": "SECRET-do-not-echo"}})

        yield SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    return GeminiQuestionPlanner(
        client_factory=client,
        model="gemini-test",
        enabled=True,
        configured=True,
        limiter=GeminiCallLimiter(30, 2),
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        (402, PlannerBillingError),
        (401, PlannerAuthenticationError),
        (403, PlannerAuthenticationError),
        (429, PlannerRateLimited),
        (500, PlannerUnavailable),
    ],
)
def test_provider_errors_classified_without_raw_message(status, expected):
    with pytest.raises(expected) as exc:
        fake_model(status).interpret("public question")
    assert "SECRET" not in str(exc.value)


@pytest.mark.asyncio
async def test_cancel_sent_gemini_holds_slot_until_worker_finishes():
    import threading

    started, release = threading.Event(), threading.Event()
    model = fake_model(500)

    def slow(question, limited):
        started.set()
        release.wait(2)
        return "{}"

    model._interpret = slow
    token = flow.set(FlowState())
    task = asyncio.create_task(model.interpret_queued("question"))
    while not started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert model.limiter.active == 1 and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert model.limiter.active == 0
    flow.reset(token)


@pytest.mark.asyncio
async def test_gemini_explicit_429_retries_once_and_releases_slot_during_wait(monkeypatch):
    model = fake_model(429)
    calls, waits = [], []

    def limited(question, limited):
        calls.append(question)
        error = PlannerRateLimited()
        error.retry_after = 1
        raise error

    async def wait_retry(seconds, provider, limiter):
        waits.append((seconds, provider, limiter.active))

    model._interpret = limited
    monkeypatch.setattr("newsroom_agent.request_flow.wait_retry", wait_retry)
    token = flow.set(FlowState())
    with pytest.raises(PlannerRateLimited):
        await model.interpret_queued("question")
    assert len(calls) == 2 and waits == [(1, "gemini", 0)]
    assert model.limiter.active == 0
    flow.reset(token)


@pytest.mark.asyncio
async def test_real_asgi_disconnect_cancels_pending_operation():
    gate = EventAdmission()
    started, disconnected, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def operation():
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    async def receive():
        await started.wait()
        disconnected.set()
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    response = gate.response(operation)
    await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)
    await asyncio.wait_for(stopped.wait(), 1)
    await asyncio.sleep(0.01)
    assert disconnected.is_set() and gate.active == 0


@pytest.mark.asyncio
async def test_public_http_429_retries_only_once_with_explicit_delay(monkeypatch):
    calls = []

    async def transport(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1"})

    waits = []

    async def wait_retry(seconds, provider, limiter=None):
        waits.append((seconds, provider))

    monkeypatch.setattr("newsroom_agent.request_flow.wait_retry", wait_retry)
    token = flow.set(FlowState())
    client = KosisClient(
        "test-key",
        enabled=True,
        transport=httpx.MockTransport(transport),
        limiter=PublicDataCallLimiter("kosis", 30, 2),
    )
    from newsroom_agent.providers.kosis_employment import KosisError

    with pytest.raises(KosisError):
        await client.fetch_parameters({})
    assert len(calls) == 2 and waits == [(1, "kosis")]
    flow.reset(token)


@pytest.mark.asyncio
async def test_public_daily_quota_does_not_retry():
    calls = []

    async def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"err": "40"})

    token = flow.set(FlowState())
    client = KosisClient("test-key", enabled=True, transport=httpx.MockTransport(transport))
    from newsroom_agent.providers.kosis_employment import KosisError

    with pytest.raises(KosisError):
        await client.fetch_parameters({})
    assert len(calls) == 1
    flow.reset(token)


@pytest.mark.asyncio
async def test_admission_bound_terminal_error_and_release():
    gate = EventAdmission(maximum=1, total_seconds=0.02)

    async def hanging():
        await asyncio.sleep(10)

    response = gate.response(hanging)
    with pytest.raises(HTTPException) as exc:
        gate.response(hanging)
    assert exc.value.status_code == 429
    events = [json.loads(x) async for x in response.body_iterator]
    assert events[0]["type"] == "progress"
    assert events[-1]["detail"]["code"] == "request_timeout"
    await asyncio.sleep(0.01)
    assert gate.active == 0


@pytest.mark.asyncio
async def test_disconnect_cancels_operation_and_releases_admission():
    stopped = asyncio.Event()
    gate = EventAdmission()

    async def operation():
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    response = gate.response(operation)
    await anext(response.body_iterator)
    await asyncio.sleep(0)
    await response.body_iterator.aclose()
    await asyncio.wait_for(stopped.wait(), 1)
    await asyncio.sleep(0.01)
    assert gate.active == 0


def test_snapshot_stream_requires_approval_and_preserves_contract():
    saved = load_snapshots()["seoul"]["result"]
    body = {
        "question": saved["question"],
        "conditions": saved["conditions"],
        "mode": "snapshot",
        "snapshot_id": "seoul",
        "approved": True,
    }
    with TestClient(main.app) as client:
        for route in ["execute", "general"]:
            r = client.post(f"/api/v1/event/{route}/stream", json=body)
            assert r.status_code == 200
            events = [json.loads(line) for line in r.text.splitlines()]
            assert events[0]["type"] == "progress" and events[-1]["type"] == "result"
            assert all(e["request_id"] == r.headers["X-Request-ID"] for e in events)
            assert events[-1]["result"]["conditions"] == body["conditions"]
            assert events[-1]["result"]["data_mode"] == "snapshot"
        assert (
            client.post("/api/v1/event/execute/stream", json=body | {"approved": False}).status_code
            == 422
        )
        assert client.get("/api/v1/event/queue").json()["active_requests"] == 0


def test_stream_access_checked_before_work(monkeypatch):
    monkeypatch.setattr(main.settings, "workshop_access_code", "test-access-code-long-enough")
    with TestClient(main.app) as client:
        for path in ["plan/stream", "execute/stream", "general/stream", "queue"]:
            r = (
                client.get("/api/v1/event/" + path)
                if path == "queue"
                else client.post("/api/v1/event/" + path, json={})
            )
            assert r.status_code == 401


@pytest.mark.asyncio
async def test_deadline_returns_error_before_sent_call_cleanup_completes():
    gate = EventAdmission(total_seconds=0.02)
    release = asyncio.Event()

    async def operation():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await release.wait()
            raise

    response = gate.response(operation)

    async def consume():
        return [json.loads(x) async for x in response.body_iterator]

    events = await asyncio.wait_for(consume(), 0.5)
    assert events[-1]["detail"]["code"] == "request_timeout"
    assert gate.active == 1  # Already-sent call still owns its slot.
    release.set()
    await asyncio.sleep(0.01)
    assert gate.active == 0


@pytest.mark.asyncio
async def test_immediate_reapproval_does_not_join_cancelled_shared_fetch():
    cache = PublicDataCache()
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def old_loader():
        entered.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cleanup.set()
            await release.wait()
            raise

    async def new_loader():
        await asyncio.sleep(0.02)
        return "new official result"

    token = flow.set(FlowState())
    first = asyncio.create_task(cache.get(("same",), old_loader))
    await entered.wait()
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    await cleanup.wait()
    second = asyncio.create_task(cache.get(("same",), new_loader))
    await asyncio.sleep(0)
    release.set()
    await asyncio.sleep(0.01)
    assert ("same",) in cache._inflight
    result, metadata = await second
    assert result == "new official result" and metadata.status == "miss"
    assert not cache._waiters and not cache._inflight
    flow.reset(token)
    await cache.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code",
    [
        (PlannerBillingError(), "planner_billing"),
        (PlannerRateLimited(), "planner_rate_limited"),
        (PlannerAuthenticationError(), "planner_configuration_error"),
    ],
)
async def test_stream_error_contract_does_not_expose_exception(error, code):
    gate = EventAdmission()

    async def fail():
        raise error

    response = gate.response(lambda: main.research_call(fail()))
    events = [json.loads(x) async for x in response.body_iterator]
    assert events[-1]["type"] == "error" and events[-1]["detail"]["code"] == code
    await asyncio.sleep(0.01)
    assert gate.active == 0
