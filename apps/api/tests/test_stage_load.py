"""Offline tests of the manual load driver, including the real ASGI contracts."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from newsroom_agent import main

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("stage_load", ROOT / "scripts/stage_load.py")
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)
CODE = "offline-test-workshop-code-only"
ORIGIN = "https://stage.example.test"


@pytest.fixture
def stage(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "stage")
    monkeypatch.setattr(main.settings, "workshop_access_code", CODE)
    monkeypatch.setattr(main.settings, "live_api_enabled", False)
    monkeypatch.setattr(main.settings, "public_data_mode", "mock")
    monkeypatch.setattr(main.settings, "fallback_snapshot_enabled", True)

    def forbidden(*args, **kwargs):
        pytest.fail("Load checks must not construct providers or consume their quotas")

    for name in ("KosisClient", "OpenDartClient", "get_public_data_limiter", "get_gemini_limiter"):
        monkeypatch.setattr(main, name, forbidden)
    return httpx.ASGITransport(app=main.app)


@pytest.mark.asyncio
async def test_real_contracts_at_concurrency_include_all_modes_edits_and_no_live_calls(stage):
    outgoing = []

    async def handle(request):
        body = json.loads(request.content) if request.content else None
        outgoing.append((request.url.path, body))
        return await stage.handle_async_request(request)

    report = await load.run_suite(ORIGIN, CODE, pause=0,
                                  transport=httpx.MockTransport(handle))
    assert report["passed"] is True
    assert report["http_requests"] == 766
    for result in report["stages"]:
        assert sum(result["completed_flows"].values()) == result["users"] * 4
        assert set(result["completed_flows"].values()) == {result["users"]}
        assert result["peak_client_requests"] == result["users"]
        assert result["metrics"]["guard.unapproved"]["statuses"] == {"422": 4}
        assert all(metric["unexpected"] == 0 for metric in result["metrics"].values())
    assert all(body["mode"] in ("mock", "snapshot") for _, body in outgoing if body)
    assert all(body["interpretation_method"] == "mock_rules"
               for path, body in outgoing if path.endswith("/plan"))
    approvals = [body for path, body in outgoing if path.endswith("/execute") and body["approved"]]
    assert len(approvals) == 408
    assert sum(body["conditions"]["comparison"] == "증감률" for body in approvals) == 204
    serialized = json.dumps(report)
    assert all(value not in serialized for value in (CODE, "query_plan", "raw_values"))
    assert ORIGIN not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,value,reason", [
    ("live_api_enabled", True, "unsafe_stage_settings"),
    ("app_env", "event", "unsafe_stage_settings"),
    ("public_data_mode", "live", "unsafe_stage_settings"),
    ("workshop_access_code", "", "unsafe_access_status"),
    ("fallback_snapshot_enabled", False, "snapshot_unavailable"),
])
async def test_unsafe_target_aborts_before_participants(stage, monkeypatch, setting, value, reason):
    monkeypatch.setattr(main.settings, setting, value)
    report = await load.run_suite(ORIGIN, CODE, transport=stage, pause=0)
    assert not report["passed"] and len(report["stages"]) == 1
    assert report["stages"][0]["failure"] == reason
    assert not any(label.startswith("load.") for label in report["stages"][0]["metrics"])


@pytest.mark.asyncio
@pytest.mark.parametrize("fault,reason", [
    ("redirect", "unexpected_http_status"),
    ("server_error", "unexpected_http_status"),
    ("early_result", "result_before_approval"),
    ("wrong_approval", "approved_conditions_mismatch"),
    ("verified", "review_status_changed"),
    ("wrong_id", "request_id_mismatch"),
    ("timeout", "transport_or_timeout"),
])
async def test_faults_stop_ramp_without_retry_or_sensitive_reports(stage, fault, reason):
    calls = []
    injected = False

    async def handle(request):
        nonlocal injected
        calls.append(request.url.path)
        target = "/plan" if fault == "early_result" else "/execute"
        body = json.loads(request.content) if request.content else {}
        if not injected and request.url.path.endswith(target) and (
            target == "/plan" or body.get("approved") is True
        ):
            injected = True
            if fault == "redirect":
                return httpx.Response(307, headers={"location": "https://other.example/" + CODE})
            if fault == "server_error":
                return httpx.Response(500, text=CODE)
            if fault == "timeout":
                raise httpx.ReadTimeout(CODE, request=request)
            response = await stage.handle_async_request(request)
            await response.aread()
            payload = response.json()
            if fault == "early_result":
                payload["evidence"] = {"private": CODE}
            elif fault == "wrong_approval":
                payload["query_plan"]["comparison"] = CODE
            elif fault == "verified":
                payload["brief"]["verification_status"] = "reviewed"
            elif fault == "wrong_id":
                payload["request_id"] = CODE
            return httpx.Response(200, json=payload, headers={"X-Request-ID": response.headers[
                "X-Request-ID"]})
        return await stage.handle_async_request(request)

    report = await load.run_suite(ORIGIN, CODE, transport=httpx.MockTransport(handle), pause=0)
    assert not report["passed"] and len(report["stages"]) == 1
    assert report["stages"][0]["failure"] == reason
    assert report["stages"][0]["completed_flows"] == {}
    assert CODE not in json.dumps(report)
    assert len(calls) <= 16


@pytest.mark.asyncio
async def test_deadline_cancels_pending_requests_and_stops_ramp():
    cancelled = False

    async def stalled(request):
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True

    report = await load.run_suite(
        ORIGIN, CODE, transport=httpx.MockTransport(stalled), deadline=0.01,
    )
    assert cancelled
    assert report["stages"][0]["failure"] == "stage_deadline"
    assert report["http_requests"] == 1


@pytest.mark.asyncio
async def test_latency_threshold_fails_and_stops_ramp(stage, monkeypatch):
    # Exercise reporting with a deterministic threshold, without a slow/flaky sleep-based test.
    monkeypatch.setattr(load, "P95_LIMIT_MS", -1)
    report = await load.run_suite(ORIGIN, CODE, transport=stage, pause=0)
    assert not report["passed"] and len(report["stages"]) == 1
    assert report["stages"][0]["failure"] == "p95_above_target"


@pytest.mark.asyncio
@pytest.mark.parametrize("stages", [(31,), (0,), (True,), (30, 1), (1, 1), (), (1, 2, 3, 4, 5)])
async def test_load_bounds_reject_before_any_network(stages):
    with pytest.raises(load.CheckFailed, match="invalid_stages"):
        await load.run_suite(ORIGIN, CODE, stages=stages)


@pytest.mark.parametrize("origin", ["http://stage.test", "https://user:secret@stage.test",
                                    "https://stage.test/?code=secret", "https://stage.test/path",
                                    "https://stage.test/#secret"])
def test_origin_never_carries_credentials_or_uses_plain_http(origin):
    with pytest.raises(load.CheckFailed):
        load.validate_origin(origin)


def test_percentile_uses_nearest_rank_and_expected_rejections_are_not_errors():
    assert load.percentile(list(range(1, 101)), 0.95) == 95
    summary = load.summarize([
        {"label": "guard", "expected": 422, "status": 422, "duration_ms": 5},
        {"label": "guard", "expected": 422, "status": 500, "duration_ms": 10},
    ])
    assert summary["guard"]["unexpected"] == 1
    assert summary["guard"]["p95_ms"] == 10
