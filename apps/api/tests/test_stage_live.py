"""Real Gemini SDK plus live adapters through mocked transports; never actual API calls."""

import importlib
import json
from pathlib import Path

import httpx
import pytest
from google.genai import types
from test_cached_execution import BODY
from test_cached_execution import environment as environment  # reusable offline adapter fixture

from newsroom_agent import main
from newsroom_agent.providers import gemini

ROOT = Path(__file__).resolve().parents[3]
CODE = "stage-live-offline-access-code"


@pytest.fixture
def live_environment(environment, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    script = importlib.import_module("stage_live")
    for key, value in {"app_env": "stage", "workshop_access_code": CODE,
                       "gemini_planner_enabled": True, "gemini_auth_mode": "api_key",
                       "gemini_api_key": "offline-gemini-key", "fallback_snapshot_enabled": True,
                       "cache_ttl_seconds": 3600}.items():
        monkeypatch.setattr(main.settings, key, value)
    environment.model_calls = []
    environment.model_error = False

    def handle(request):
        environment.model_calls.append(request)
        if environment.model_error:
            return httpx.Response(503, json={"error": {"code": 503, "message": CODE}})
        question = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        source = "opendart" if "삼성전자" in question else "kosis"
        payload = {**BODY[source]["conditions"], "uncertain_fields": []}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "role": "model", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}],
        }}]})

    original = gemini.GeminiProvider
    clients = []

    def provider(**kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        clients.append(client)
        kwargs["http_options"] = types.HttpOptions(
            httpx_client=client, retry_options=types.HttpRetryOptions(attempts=1),
        )
        return original(**kwargs)

    monkeypatch.setattr(gemini, "GeminiProvider", provider)
    environment.script = script
    yield environment
    for client in clients:
        client.close()


@pytest.mark.asyncio
async def test_two_live_flows_preserve_approval_cache_and_snapshot_without_reinterpreting(
    live_environment,
):
    env = live_environment
    report = await env.script.run_live("https://stage.test", CODE,
                                       transport=httpx.ASGITransport(app=main.app))
    assert report["passed"] and report["http_requests"] == 19
    assert report["gemini_plan_attempts"] == len(env.model_calls) == 2
    assert len(env.calls) == 3  # one KOSIS + two OpenDART; none for plan/unapproved/snapshot/cache
    assert report["live_execution_attempts"] == {"kosis": 2, "opendart": 2}
    assert report["cache_statuses"] == {"kosis": ["miss", "hit"], "opendart": ["miss", "hit"]}
    assert len(report["request_ids"]) == 19
    assert not any(word in json.dumps(report) for word in (
        CODE, "offline-gemini-key", "offline-kosis-key", "raw_values", "삼성전자", "query_plan",
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("app_env", "local"), ("live_api_enabled", False), ("public_data_mode", "mock"),
    ("workshop_access_code", ""), ("gemini_api_key", ""), ("public_data_cache_enabled", False),
    ("fallback_snapshot_enabled", False),
])
async def test_failed_preflight_never_calls_any_provider(
    live_environment, monkeypatch, field, value,
):
    env = live_environment
    monkeypatch.setattr(main.settings, field, value)
    report = await env.script.run_live("https://stage.test", CODE,
                                       transport=httpx.ASGITransport(app=main.app))
    assert not report["passed"] and not env.calls and not env.model_calls
    assert report["gemini_plan_attempts"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [
    "gemini", "public_data", "conditions", "early_result", "meaning",
])
async def test_failure_stops_without_retry_or_silent_fallback(live_environment, fault):
    env = live_environment
    env.model_error = fault == "gemini"
    env.fail = fault == "public_data"
    base = httpx.ASGITransport(app=main.app)

    async def handle(request):
        response = await base.handle_async_request(request)
        await response.aread()
        payload = response.json()
        if (response.status_code == 200 and request.url.path.endswith("/execute")
            and fault == "conditions"):
            payload["query_plan"]["period"] = CODE
        if response.status_code == 200 and request.url.path.endswith("/plan"):
            if fault == "early_result":
                payload["brief"] = {"private": CODE}
            if fault == "meaning":
                payload["query_plan"]["period"] = "2021-2024"
        return httpx.Response(response.status_code, json=payload,
                              headers={"X-Request-ID": response.headers["X-Request-ID"]})

    report = await env.script.run_live("https://stage.test", CODE,
                                       transport=httpx.MockTransport(handle))
    assert not report["passed"] and not report["completed_sources"]
    assert len(env.model_calls) == 1 and len(env.calls) <= 1
    assert "saved.plan" not in report["metrics"]
    assert CODE not in json.dumps(report)
