"""Rehearse provider faults and stage fail-closed recovery without external I/O."""

import copy
import importlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.mock_planner import MockQuestionPlanner
from newsroom_agent.providers.opendart import OpenDartClient

ROOT = Path(__file__).resolve().parents[3]
QUESTIONS = {
    "kosis": "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교",
    "opendart": "삼성전자 2022-2024년 연간 연결 매출액 증감 폭 비교",
}
FIELDS = ("selected_source", "entity", "metric", "period", "comparison", "filters")
CODE = "offline-rehearsal-access-code"


@pytest.mark.parametrize("source", QUESTIONS)
@pytest.mark.parametrize("fault,status", [("timeout", 503), ("unavailable", 503),
                                         ("rate_limited", 429)])
def test_real_adapter_fault_then_preserved_snapshot_requires_new_approval(
    monkeypatch, source, fault, status,
):
    for key, value in {
        "live_api_enabled": True, "public_data_mode": "live", "opendart_enabled": True,
        "kosis_enabled": True, "opendart_api_key": "offline-test-key",
        "kosis_api_key": "offline-test-key", "public_data_cache_enabled": False,
        "fallback_snapshot_enabled": True, "workshop_access_code": CODE,
    }.items():
        monkeypatch.setattr(main.settings, key, value)
    calls = []

    def transport(request):
        calls.append(request.url.path)
        if fault == "timeout":
            raise httpx.ReadTimeout("private-provider-detail", request=request)
        return httpx.Response(status)

    monkeypatch.setattr(main, "KosisClient", lambda *a, **kw: KosisClient(
        "offline-test-key", enabled=True, transport=httpx.MockTransport(transport),
    ))
    monkeypatch.setattr(main, "OpenDartClient", lambda *a, **kw: OpenDartClient(
        "offline-test-key", enabled=True, transport=httpx.MockTransport(transport),
    ))
    monkeypatch.setattr(main, "get_gemini_limiter", lambda *a: pytest.fail("No Gemini call"))
    with TestClient(main.app, headers={"X-Workshop-Code": CODE}) as client:
        question = QUESTIONS[source]
        plan = client.post("/api/v1/plan", json={"question": question, "mode": "live"}).json()
        conditions = {key: copy.deepcopy(plan["query_plan"][key]) for key in FIELDS}
        conditions["comparison"] = "증감률"
        if source == "kosis":
            conditions.update(entity="수도권 시·도", period="2021-2024")
        live = {"question": question, "mode": "live", "conditions": conditions, "approved": True}
        assert not calls
        assert client.post("/api/v1/execute", json={**live, "approved": False}).status_code == 422
        assert not calls
        failed = client.post("/api/v1/execute", json=live)
        assert failed.status_code == status
        assert failed.json()["detail"]["code"] == f"{source}_{fault}"
        assert set(failed.json()) == {"detail"}
        assert failed.headers["X-Request-ID"]
        assert all(value not in failed.text for value in (CODE, "private-provider-detail"))
        assert len(calls) == 1

        monkeypatch.setattr(MockQuestionPlanner, "interpret", lambda *a: pytest.fail("No re-parse"))
        prepared = client.post("/api/v1/plan", json={"question": question, "mode": "snapshot",
                                                   "conditions": conditions}).json()
        assert prepared["conditions_preserved"]
        assert {key: prepared["query_plan"][key] for key in FIELDS} == conditions
        assert not {"evidence", "brief", "calculation"}.intersection(prepared)
        assert len(calls) == 1
        saved = {**live, "mode": "snapshot", "snapshot_id": prepared["snapshot"]["snapshot_id"]}
        assert client.post("/api/v1/execute", json={**saved, "approved": False}).status_code == 422
        stale = client.post("/api/v1/execute", json={**saved, "snapshot_id": "old-version"})
        assert stale.status_code == 409 and set(stale.json()) == {"detail"}
        recovered = client.post("/api/v1/execute", json=saved)
        assert recovered.status_code == 200
        result = recovered.json()
        assert result["request_id"] == recovered.headers["X-Request-ID"]
        assert result["request_id"] != failed.headers["X-Request-ID"]
        assert result["snapshot"] == prepared["snapshot"]
        assert result["evidence"]["data_mode"] == "snapshot" and result["cache"] is None
        assert result["evidence"]["retrieved_at"] == prepared["snapshot"]["captured_at"]
        assert result["brief"]["verification_status"] == "review_required"
        assert {key: result["query_plan"][key] for key in FIELDS} == conditions
        assert len(calls) == 1  # neither retries nor automatic provider requests on fallback


@pytest.fixture
def rehearsal(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("stage_rehearsal")
    for key, value in {"app_env": "stage", "workshop_access_code": CODE,
                       "live_api_enabled": False, "public_data_mode": "mock",
                       "fallback_snapshot_enabled": True}.items():
        monkeypatch.setattr(main.settings, key, value)

    def forbidden(*a, **kw):
        pytest.fail("Stage rehearsal must stop before any provider or live quota")

    for name in ("KosisClient", "OpenDartClient", "get_public_data_limiter", "get_gemini_limiter"):
        monkeypatch.setattr(main, name, forbidden)
    return module


@pytest.mark.asyncio
async def test_stage_rehearsal_has_bounded_calls_and_report_contains_no_payloads(rehearsal):
    report = await rehearsal.run_rehearsal("https://stage.test", CODE,
                                         transport=httpx.ASGITransport(app=main.app))
    assert report["passed"] and report["completed_sources"] == list(QUESTIONS)
    assert report["http_requests"] == 27
    assert report["metrics"]["drill.live_disabled"]["statuses"] == {"503": 4}
    assert report["metrics"]["drill.stale_snapshot"]["statuses"] == {"409": 2}
    assert all(stat["unexpected"] == 0 for stat in report["metrics"].values())
    assert all(value not in json.dumps(report) for value in (CODE, "raw_values", "query_plan"))


@pytest.mark.asyncio
async def test_stage_rehearsal_refuses_live_before_sending_a_live_body(rehearsal, monkeypatch):
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    report = await rehearsal.run_rehearsal("https://stage.test", CODE,
                                         transport=httpx.ASGITransport(app=main.app))
    assert not report["passed"] and report["http_requests"] == 1
    assert report["failure"] == "unsafe_stage_settings"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["wrong_error", "lost_conditions", "early_brief"])
async def test_stage_rehearsal_rejects_invalid_recovery_without_saving_response(rehearsal, fault):
    transport = httpx.ASGITransport(app=main.app)

    async def handle(request):
        response = await transport.handle_async_request(request)
        await response.aread()
        payload = response.json()
        if response.status_code == 503 and fault == "wrong_error":
            payload["detail"]["code"] = CODE
        body = json.loads(request.content) if request.content else {}
        if body.get("conditions") and body.get("mode") == "snapshot" and request.url.path.endswith(
            "/plan"
        ):
            if fault == "lost_conditions":
                payload["query_plan"]["comparison"] = CODE
            if fault == "early_brief":
                payload["brief"] = {"private": CODE}
        return httpx.Response(response.status_code, json=payload,
                              headers={"X-Request-ID": response.headers["X-Request-ID"]})

    report = await rehearsal.run_rehearsal("https://stage.test", CODE,
                                         transport=httpx.MockTransport(handle))
    assert not report["passed"] and not report["completed_sources"]
    assert CODE not in json.dumps(report)
