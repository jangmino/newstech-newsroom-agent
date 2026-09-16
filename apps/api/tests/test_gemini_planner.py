import json
import logging
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from google import genai
from google.genai import types

from newsroom_agent import main
from newsroom_agent.planning import InvalidPlannerOutput, create_plan
from newsroom_agent.providers.gemini import GeminiProvider
from newsroom_agent.providers.gemini_planner import GeminiCallLimiter, GeminiQuestionPlanner
from newsroom_agent.providers.planner import (
    PlannerConfigurationError,
    PlannerDisabled,
    PlannerRateLimited,
    PlannerTimedOut,
    PlannerUnavailable,
)

QUESTION = "전국 시·도 청년 고용률 2020-2024 증감 폭 15-29세 연간 비교"


def candidate():
    return {
        "selected_source": "kosis", "entity": "전국 시·도", "metric": "고용률",
        "period": "2020-2024", "comparison": "증감 폭",
        "filters": {"age_range": "15-29세", "frequency": "연간"}, "uncertain_fields": [],
    }


def response_body(raw=None, finish="STOP"):
    return {"candidates": [{
        "content": {"role": "model", "parts": [{
            "text": json.dumps(candidate(), ensure_ascii=False) if raw is None else raw,
        }]}, "finishReason": finish,
    }]}


@contextmanager
def sdk_planner(handler, **overrides):
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as transport_client:
        options = types.HttpOptions(
            httpx_client=transport_client, timeout=1250,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        provider = GeminiQuestionPlanner(**({
            "client_factory": lambda: GeminiProvider(
                auth_mode="api_key", api_key="test-only", http_options=options,
            ).client,
            "model": "gemini-3.8-flash", "enabled": True, "configured": True,
            "limiter": GeminiCallLimiter(30, 8),
        } | overrides))
        yield provider


def test_real_sdk_serialization_is_bounded_and_separates_question_from_system_rules():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/models/gemini-3.8-flash:generateContent")
        assert "key" not in request.url.params
        assert request.headers["x-goog-api-key"] == "test-only"
        assert request.extensions["timeout"]["read"] == 1.25
        body = json.loads(request.content)
        assert body["contents"] == [{"role": "user", "parts": [{"text": QUESTION}]}]
        assert QUESTION not in json.dumps(body["systemInstruction"], ensure_ascii=False)
        assert "추측하지" in json.dumps(body["systemInstruction"], ensure_ascii=False)
        config = body["generationConfig"]
        assert config["candidateCount"] == 1 and config["maxOutputTokens"] == 2048
        assert config["responseMimeType"] == "application/json"
        schema = config["responseJsonSchema"]
        assert set(schema["required"]) == set(candidate())
        assert schema["additionalProperties"] is False
        assert "tools" not in body and "toolConfig" not in body
        return httpx.Response(200, json=response_body())

    with sdk_planner(handler) as planner:
        result = create_plan(QUESTION, planner)
    assert len(calls) == 1
    assert result.required_fields == []
    assert result.query_plan.metric == "고용률"
    assert "evidence" not in result.model_dump()


@pytest.mark.parametrize(("status", "error"), [
    (401, PlannerUnavailable), (403, PlannerUnavailable), (404, PlannerUnavailable),
    (429, PlannerRateLimited), (500, PlannerUnavailable), (503, PlannerUnavailable),
    (504, PlannerTimedOut),
])
def test_provider_failures_are_not_retried_or_exposed(status, error, caplog):
    calls = []
    caplog.set_level(logging.DEBUG)

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {
            "code": status, "message": "private-provider-error-body", "status": "UNKNOWN",
        }})

    with sdk_planner(handler) as planner, pytest.raises(error) as caught:
        planner.interpret(QUESTION)
    assert len(calls) == 1
    assert str(caught.value) == ""
    assert "private-provider-error-body" not in caplog.text
    assert "test-only" not in caplog.text


def test_transport_timeout_has_safe_error_and_releases_slot():
    calls = []
    limiter = GeminiCallLimiter(30, 1)

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-url-or-provider-detail", request=request)

    with sdk_planner(handler, limiter=limiter) as planner, pytest.raises(PlannerTimedOut) as caught:
        planner.interpret(QUESTION)
    assert len(calls) == 1 and limiter.active == 0
    assert str(caught.value) == ""


@pytest.mark.parametrize("body", [
    {}, {"promptFeedback": {"blockReason": "SAFETY"}},
    response_body() | {"promptFeedback": {"blockReason": "SAFETY"}},
    response_body(finish="MAX_TOKENS"), response_body(finish="SAFETY"),
    response_body(raw=""), response_body(raw="not json"),
    {"candidates": response_body()["candidates"] * 2},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"functionCall": {"name": "execute", "args": {}}},
    ]}}]},
])
def test_blocked_truncated_empty_or_unstructured_responses_never_become_plans(body):
    with sdk_planner(lambda request: httpx.Response(200, json=body)) as planner:
        with pytest.raises(InvalidPlannerOutput):
            create_plan(QUESTION, planner)


def test_model_uncertainty_is_validated_even_when_model_supplies_a_value():
    output = candidate()
    output["uncertain_fields"] = ["period", "filters.age_range"]
    body = response_body(raw=json.dumps(output))
    with sdk_planner(lambda request: httpx.Response(200, json=body)) as planner:
        result = create_plan(QUESTION, planner)
    assert result.query_plan.period == ""
    assert result.query_plan.filters["age_range"] == ""
    assert set(result.required_fields) == {"period", "filters.age_range"}


@pytest.mark.parametrize(("overrides", "error"), [
    ({"enabled": False}, PlannerDisabled), ({"configured": False}, PlannerConfigurationError),
    ({"model": "https://invalid.example/model"}, PlannerConfigurationError),
])
def test_disabled_or_invalid_configuration_never_creates_a_client(overrides, error):
    def forbidden():
        raise AssertionError("Client must not be constructed")

    with sdk_planner(lambda request: pytest.fail("No transport expected"),
                     client_factory=forbidden, **overrides) as planner:
        with pytest.raises(error):
            planner.interpret(QUESTION)


def test_client_setup_failure_is_safe_and_budget_slot_is_released():
    limiter = GeminiCallLimiter(2, 1)

    def broken():
        raise ValueError("private-credential-detail")

    with sdk_planner(lambda request: pytest.fail("No transport expected"),
                     client_factory=broken, limiter=limiter) as planner:
        with pytest.raises(PlannerUnavailable) as caught:
            planner.interpret(QUESTION)
    assert str(caught.value) == "" and limiter.active == 0


def test_limiter_rejects_parallel_and_excess_calls_and_expires_attempts():
    now = [100.0]
    limiter = GeminiCallLimiter(2, 1, clock=lambda: now[0])
    with limiter.slot():
        with pytest.raises(PlannerRateLimited), limiter.slot():
            pytest.fail("Concurrent request entered")
    with pytest.raises(ValueError), limiter.slot():
        raise ValueError("A failed attempt still counts")
    assert limiter.active == 0
    with pytest.raises(PlannerRateLimited), limiter.slot():
        pytest.fail("Minute budget exceeded")
    now[0] += 60
    with limiter.slot():
        assert limiter.active == 1


def test_budget_rejection_never_constructs_a_client():
    limiter = GeminiCallLimiter(1, 1)
    with limiter.slot():
        pass
    with sdk_planner(lambda request: pytest.fail("No request expected"), limiter=limiter,
                     client_factory=lambda: pytest.fail("No client expected")) as planner:
        with pytest.raises(PlannerRateLimited):
            planner.interpret(QUESTION)


def test_vertex_arguments_are_explicit_without_loading_real_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(genai, "Client", lambda **kwargs: calls.append(kwargs))
    options = types.HttpOptions(timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1))
    GeminiProvider(auth_mode="vertex_ai", project="test-project", location="test-region",
                   http_options=options)
    assert calls == [{"vertexai": True, "project": "test-project", "location": "test-region",
                      "http_options": options}]


@pytest.mark.parametrize(("live", "enabled"), [(False, False), (False, True), (True, False)])
def test_api_requires_both_server_gates_without_constructing_client(monkeypatch, live, enabled):
    monkeypatch.setattr(main.settings, "live_api_enabled", live)
    monkeypatch.setattr(main.settings, "gemini_planner_enabled", enabled)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("No Gemini client expected"))
    response = TestClient(main.app).post("/api/v1/plan", json={
        "question": QUESTION, "mode": "mock", "interpretation_method": "gemini",
    })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "planner_disabled"
    assert set(response.json()) == {"detail"}


def test_gemini_enabled_still_defaults_to_mock_and_execute_cannot_invoke_gemini(monkeypatch):
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_planner_enabled", True)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("No Gemini client expected"))
    api = TestClient(main.app)
    result = api.post("/api/v1/plan", json={"question": QUESTION}).json()
    assert result["interpretation_method"] == "mock_rules"
    assert result["interpretation_model"] is None
    body = {"question": QUESTION, "mode": "mock", "approved": True, "conditions": candidate()}
    del body["conditions"]["uncertain_fields"]
    assert api.post("/api/v1/execute", json=body).status_code == 200
    body["interpretation_method"] = "gemini"
    assert api.post("/api/v1/execute", json=body).status_code == 422


def test_missing_credentials_and_client_selected_models_are_not_accepted(monkeypatch):
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_planner_enabled", True)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("No client expected"))
    api = TestClient(main.app)
    body = {"question": QUESTION, "interpretation_method": "gemini"}
    result = api.post("/api/v1/plan", json=body).json()
    assert result["detail"]["code"] == "planner_configuration_error"
    body["model"] = "client-selected-model"
    assert api.post("/api/v1/plan", json=body).status_code == 422


def test_api_gemini_result_identifies_model_and_keeps_execution_mock(monkeypatch):
    calls = []
    monkeypatch.setattr(main.settings, "live_api_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_planner_enabled", True)
    monkeypatch.setattr(main.settings, "gemini_api_key", "test-only")
    original_client = genai.Client

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_body())

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as transport_client:
        def make_client(**kwargs):
            options = kwargs["http_options"]
            assert options.timeout == 20_000
            assert options.retry_options.attempts == 1
            assert kwargs["vertexai"] is False and kwargs["api_key"] == "test-only"
            options.httpx_client = transport_client
            return original_client(**kwargs)

        monkeypatch.setattr(genai, "Client", make_client)
        api = TestClient(main.app)
        result = api.post("/api/v1/plan", json={
            "question": QUESTION, "interpretation_method": "gemini", "mode": "mock",
        }).json()
        assert result["interpretation_method"] == "gemini"
        assert result["interpretation_model"] == "gemini-3.8-flash"
        assert "evidence" not in result and "brief" not in result
        conditions = candidate()
        del conditions["uncertain_fields"]
        executed = api.post("/api/v1/execute", json={
            "question": QUESTION, "mode": "mock", "approved": True, "conditions": conditions,
        }).json()
    assert len(calls) == 1
    assert executed["evidence"]["data_mode"] == "mock"
    assert executed["brief"]["verification_status"] == "review_required"


@pytest.mark.parametrize(("error", "code", "status"), [
    (PlannerTimedOut, "planner_timeout", 503),
    (PlannerRateLimited, "planner_rate_limited", 429),
    (PlannerConfigurationError, "planner_configuration_error", 503),
])
def test_api_errors_only_expose_safe_messages(monkeypatch, error, code, status):
    class FailedPlanner:
        def interpret(self, question):
            raise error("private-provider-detail")

    monkeypatch.setitem(main.app.dependency_overrides, main.get_question_planner, FailedPlanner)
    response = TestClient(main.app).post("/api/v1/plan", json={
        "question": QUESTION, "interpretation_method": "gemini",
    })
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert set(response.json()) == {"detail"}
    assert "private-provider-detail" not in response.text
