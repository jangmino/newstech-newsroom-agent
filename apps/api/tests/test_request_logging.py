"""Offline correlation, privacy and request isolation checks."""

import asyncio
import json
import logging
import traceback
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.providers.kosis_employment import KosisError
from newsroom_agent.providers.snapshot import load_snapshot
from newsroom_agent.public_data_limits import PublicDataLimitError
from newsroom_agent.request_logging import (
    LOGGER,
    RequestLoggingMiddleware,
    configure_request_logging,
    record_error,
    request_id,
)

QUESTIONS = {
    "kosis": "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교",
    "opendart": "삼성전자 2022-2024년 연간 연결 매출액 증감 폭 비교",
}
client = TestClient(main.app)


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    LOGGER.addHandler(caplog.handler)
    yield lambda: [json.loads(record.message) for record in caplog.records
                   if record.name == LOGGER.name]
    LOGGER.removeHandler(caplog.handler)


def body(source="kosis", mode="mock"):
    return {"question": QUESTIONS[source], "mode": mode, "approved": True, "conditions": {
        "selected_source": source, "entity": "전국 시·도" if source == "kosis" else "삼성전자",
        "metric": "고용률" if source == "kosis" else "매출액",
        "period": "2020-2024" if source == "kosis" else "2022-2024", "comparison": "증감 폭",
        "filters": {"age_range": "15-29세", "frequency": "연간"} if source == "kosis" else
                   {"statement_basis": "연결", "report_type": "연간"},
    }}


def assert_record(response, record, route):
    assert set(record) == {"timestamp", "severity", "event", "request_id", "method", "route",
                           "status_code", "duration_ms", "outcome", "error_code"}
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert UUID(record["request_id"]).version == 4
    assert record["route"] == route
    assert record["status_code"] == response.status_code
    assert record["duration_ms"] >= 0
    assert record["event"] == "http_request"
    assert record["outcome"] == "completed"


@pytest.mark.parametrize("source", QUESTIONS)
@pytest.mark.parametrize("mode", ["mock", "snapshot"])
def test_plan_execution_and_header_share_id_but_each_request_is_new(source, mode, logs):
    plan = client.post("/api/v1/plan", json={"question": QUESTIONS[source], "mode": mode})
    assert plan.status_code == 200
    assert plan.json()["request_id"] == plan.headers["X-Request-ID"]
    assert "evidence" not in plan.json()
    approved = body(source, mode)
    if mode == "snapshot":
        approved["snapshot_id"] = plan.json()["snapshot"]["snapshot_id"]
    first = client.post("/api/v1/execute", json=approved)
    second = client.post("/api/v1/execute", json=approved)
    for response, record in zip([plan, first, second], logs(), strict=True):
        assert response.status_code == 200
        assert_record(response, record, response.request.url.path)
        assert response.json()["request_id"] == record["request_id"]
        assert record["error_code"] is None and record["severity"] == "INFO"
    assert len({entry["request_id"] for entry in logs()}) == 3


def test_legacy_fields_remain_compatible_and_correlated(logs):
    response = client.post("/api/v1/analyze", json={"question": QUESTIONS["kosis"]})
    assert set(response.json()) == {"request_id", "question", "query_plan", "evidence", "brief"}
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert_record(response, logs()[0], "/api/v1/analyze")


@pytest.mark.parametrize("path", ["plan", "execute", "analyze"])
def test_validation_failures_have_id_without_logging_inputs(path, logs):
    response = client.post(f"/api/v1/{path}", json={"question": {"private-question-marker": "x"}})
    assert response.status_code == 422
    assert len(logs()) == 1
    assert_record(response, logs()[0], f"/api/v1/{path}")
    assert logs()[0]["error_code"] == "invalid_request"
    assert "private-question-marker" not in json.dumps(logs())


@pytest.mark.parametrize("code,expected", [("test-only-workshop-credential", 401), ("short", 503)])
def test_access_errors_are_correlated_before_body_processing(code, expected, monkeypatch, logs):
    monkeypatch.setattr(main.settings, "workshop_access_code", code)
    response = client.post("/api/v1/plan", content="private-body-marker")
    assert response.status_code == expected
    assert_record(response, logs()[0], "/api/v1/plan")
    assert logs()[0]["error_code"] == response.json()["detail"]["code"]
    assert code not in json.dumps(logs()) and "private-body-marker" not in json.dumps(logs())


@pytest.mark.parametrize("failure", ["timeout", "no_data", "rate", "busy"])
def test_live_failures_have_bounded_error_codes_without_provider_text(failure, monkeypatch, logs):
    for field, value in {"live_api_enabled": True, "public_data_mode": "live",
                         "kosis_enabled": True, "kosis_api_key": "test-only-api-key"}.items():
        monkeypatch.setattr(main.settings, field, value)

    async def fail(*args, **kwargs):
        if failure in {"rate", "busy"}:
            raise PublicDataLimitError("kosis", 12 if failure == "rate" else None)
        raise KosisError(failure)

    monkeypatch.setattr(main, "execute_employment", fail)
    response = client.post("/api/v1/execute", json=body(mode="live"))
    assert response.status_code == (429 if failure in {"rate", "busy"} else 503)
    assert_record(response, logs()[0], "/api/v1/execute")
    assert logs()[0]["error_code"] == response.json()["detail"]["code"]
    assert "test-only-api-key" not in json.dumps(logs())
    if failure == "rate":
        assert response.headers["Retry-After"] == "12"


def test_snapshot_error_is_logged_without_file_details(monkeypatch, logs):
    monkeypatch.setattr(main.settings, "fallback_snapshot_enabled", False)
    response = client.post("/api/v1/plan", json={
        "question": QUESTIONS["kosis"], "mode": "snapshot",
    })
    assert response.status_code == 503
    assert logs()[0]["error_code"] == "snapshot_disabled"
    assert_record(response, logs()[0], "/api/v1/plan")


def test_unexpected_exception_becomes_safe_500_with_id_and_cors(monkeypatch, logs, caplog):
    def fail():
        raise RuntimeError("private-exception-marker?key=test-only-secret")

    monkeypatch.setitem(main.app.dependency_overrides, main.get_question_planner, fail)
    response = client.post("/api/v1/plan", json={"question": QUESTIONS["kosis"]},
                           headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert "문의용 요청 번호" in response.json()["detail"]["message"]
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    assert response.headers["Cache-Control"] == "no-store"
    assert_record(response, logs()[0], "/api/v1/plan")
    assert logs()[0]["severity"] == "ERROR" and logs()[0]["error_code"] == "internal_error"
    assert "private-exception-marker" not in response.text + caplog.text


def test_path_query_headers_and_client_id_are_never_logged(logs):
    supplied_id = "e4d3ff85-6883-4a53-b20b-ecf2ad1f2899"
    response = client.get("/private-path-marker?key=private-query-marker", headers={
        "X-Request-ID": supplied_id, "Authorization": "Bearer private-header-marker",
        "X-Workshop-Code": "private-code-marker", "User-Agent": "private-agent-marker",
    })
    assert response.status_code == 404
    assert_record(response, logs()[0], "other")
    assert logs()[0]["error_code"] == "not_found"
    text = json.dumps(logs())
    assert "private-" not in text and supplied_id not in text
    assert response.headers["X-Request-ID"] != supplied_id


def test_unknown_method_and_error_code_cannot_inject_logs(monkeypatch, logs):
    response = client.request("PRIVATE-METHOD-MARKER", "/health")
    assert response.status_code == 405
    assert logs()[0]["method"] == "OTHER"

    def fail():
        raise HTTPException(503, {"code": "private-code-marker\nforged-log", "message": "hidden"})

    monkeypatch.setitem(main.app.dependency_overrides, main.get_question_planner, fail)
    client.post("/api/v1/plan", json={"question": QUESTIONS["kosis"]})
    assert logs()[-1]["error_code"] == "http_error"
    assert "private-code-marker" not in json.dumps(logs())


def test_cors_preflight_and_allowed_response_expose_correlation(logs):
    preflight = client.options("/api/v1/plan", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Workshop-Code",
    })
    assert preflight.status_code == 200
    assert_record(preflight, logs()[0], "/api/v1/plan")
    response = client.get("/api/v1/access", headers={"Origin": "http://localhost:5173"})
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    assert_record(response, logs()[1], "/api/v1/access")


@pytest.mark.asyncio
async def test_concurrent_sync_plans_do_not_mix_ids_or_error_metadata(logs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="http://test") as api:
        responses = await asyncio.gather(*[
            api.post("/api/v1/plan", json={"question": QUESTIONS["kosis"]}) for _ in range(12)
        ])
    by_id = {entry["request_id"]: entry for entry in logs()}
    assert len(by_id) == len(responses) == 12
    for response in responses:
        assert response.status_code == 200
        identifier = response.headers["X-Request-ID"]
        assert response.json()["request_id"] == identifier
        assert by_id[identifier]["error_code"] is None
    assert request_id() != request_id()  # Context was restored outside requests.


@pytest.mark.asyncio
async def test_shared_live_cache_keeps_distinct_request_ids(monkeypatch, logs):
    for field, value in {"live_api_enabled": True, "public_data_mode": "live",
                         "kosis_enabled": True, "kosis_api_key": "test-only-api-key",
                         "public_data_cache_enabled": True}.items():
        monkeypatch.setattr(main.settings, field, value)
    calls = []

    class FakeKosis:
        async def fetch_employment(self, query):
            calls.append(query)
            await asyncio.sleep(0.02)
            return load_snapshot("kosis").employment

    monkeypatch.setattr(main, "KosisClient", lambda *args, **kwargs: FakeKosis())
    async with main.lifespan(main.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test",
    ) as api:
        responses = await asyncio.gather(*[
            api.post("/api/v1/execute", json=body(mode="live")) for _ in range(6)
        ])
    assert len(calls) == 1 and len(logs()) == 6
    assert len({response.json()["request_id"] for response in responses}) == 6
    assert {response.json()["cache"]["status"] for response in responses} == {"miss", "coalesced"}
    for response in responses:
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancelled", "partial"])
async def test_cancellation_and_partial_response_are_not_logged_as_success(failure, logs):
    async def fail(scope, receive, send):
        if failure == "cancelled":
            raise asyncio.CancelledError()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{", "more_body": True})
        raise ValueError("private-stream-failure")

    sent = []

    async def send(message):
        sent.append(message)

    middleware = RequestLoggingMiddleware(fail, [])
    error = asyncio.CancelledError if failure == "cancelled" else RuntimeError
    with pytest.raises(error) as caught:
        await middleware({"type": "http", "method": "GET", "path": "/health", "headers": []},
                         None, send)
    assert "private-stream-failure" not in "".join(traceback.format_exception(caught.value))
    assert logs()[0]["outcome"] == ("cancelled" if failure == "cancelled" else "interrupted")
    assert len(logs()) == 1
    assert request_id() != request_id()
    if failure == "cancelled":
        assert logs()[0]["status_code"] is None


def test_logger_configuration_is_idempotent_and_default_access_logging_is_off(logs):
    count = len(LOGGER.handlers)
    configure_request_logging()
    configure_request_logging()
    assert len(LOGGER.handlers) == count
    assert LOGGER.propagate is False
    assert logging.getLogger("uvicorn.access").disabled
    record_error("private-marker")  # Safe no-op outside an HTTP request.
    assert logs() == []
