"""Synthetic credentials only; no environment files or external calls."""

import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.workshop_access import WorkshopAccessMiddleware

CODE = "test-only-workshop-credential"
HEADERS = {"X-Workshop-Code": CODE}
QUESTION = "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교"
client = TestClient(main.app)


@pytest.fixture(autouse=True)
def protect(monkeypatch):
    monkeypatch.setattr(main.settings, "workshop_access_code", CODE)


@pytest.mark.parametrize("path", ["plan", "execute", "analyze", "access", "future-route"])
@pytest.mark.parametrize("headers", [{}, {"X-Workshop-Code": "incorrect-test-value"},
                                    [("X-Workshop-Code", CODE), ("X-Workshop-Code", CODE)]])
def test_missing_wrong_duplicate_codes_block_before_validation(path, headers, caplog):
    response = client.post(f"/api/v1/{path}", content="not-json", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "workshop_access_required"
    assert response.json()["detail"]["field_errors"] == {}
    assert response.headers["Cache-Control"] == "no-store"
    assert "X-Workshop-Code" in response.headers["Vary"]
    assert CODE not in response.text + caplog.text


@pytest.mark.parametrize("mode", ["mock", "snapshot", "live"])
def test_all_modes_block_before_planner_cache_or_provider(mode, monkeypatch):
    def forbidden():
        raise AssertionError("No dependency may run without access")
    monkeypatch.setitem(main.app.dependency_overrides, main.get_question_planner, forbidden)
    response = client.post("/api/v1/plan", json={
        "question": QUESTION, "mode": mode, "interpretation_method": "gemini",
    })
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
                                  "/api/v1/plan/", "/api"])
def test_documentation_and_slash_paths_are_protected(path):
    assert client.get(path, follow_redirects=False).status_code == 401


def test_public_status_health_and_preflight_never_disclose_code():
    response = client.get("/api/v1/access")
    assert response.json() == {"required": True, "available": True}
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/health").status_code == 200
    cors = client.options("/api/v1/plan", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type,X-Workshop-Code",
    })
    assert cors.status_code == 200
    assert cors.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    unauthorized = client.post("/api/v1/plan", headers={"Origin": "http://localhost:5173"})
    assert unauthorized.status_code == 401
    assert unauthorized.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert CODE not in response.text + cors.text


@pytest.mark.parametrize("environment", ["local", "test", "stage", "event", "production", "typo"])
def test_blank_code_only_disables_protection_in_local_or_test(environment, monkeypatch):
    monkeypatch.setattr(main.settings, "workshop_access_code", "")
    monkeypatch.setattr(main.settings, "app_env", environment)
    disabled = environment in {"local", "test"}
    assert client.get("/api/v1/access").json() == {
        "required": not disabled, "available": disabled,
    }
    response = client.post("/api/v1/analyze", json={"question": QUESTION})
    assert response.status_code == (200 if disabled else 503)
    if not disabled:
        assert response.json()["detail"]["code"] == "workshop_access_unavailable"


@pytest.mark.parametrize("value", [" ", "short", "한글" * 16, CODE + " ", "x" * 129])
def test_bad_configuration_fails_closed_even_locally(value, monkeypatch):
    monkeypatch.setattr(main.settings, "workshop_access_code", value)
    monkeypatch.setattr(main.settings, "app_env", "local")
    assert client.get("/api/v1/access").json() == {"required": True, "available": False}
    response = client.post("/api/v1/access", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "workshop_access_unavailable"


@pytest.mark.parametrize("mode", ["mock", "snapshot"])
def test_authorized_plan_and_separate_approval_keep_contracts(mode, caplog):
    entered = client.post("/api/v1/access", headers=HEADERS)
    assert entered.status_code == 200
    assert entered.json() == {"required": True, "available": True}
    response = client.post("/api/v1/plan", headers=HEADERS, json={
        "question": QUESTION, "mode": mode,
    })
    assert response.status_code == 200
    plan = response.json()
    assert "evidence" not in plan and "brief" not in plan
    conditions = {key: plan["query_plan"][key] for key in
                  ("selected_source", "entity", "metric", "period", "comparison", "filters")}
    body = {"question": QUESTION, "mode": mode, "conditions": conditions, "approved": False}
    if mode == "snapshot":
        body["snapshot_id"] = plan["snapshot"]["snapshot_id"]
    assert client.post("/api/v1/execute", headers=HEADERS, json=body).status_code == 422
    body["approved"] = True
    result = client.post("/api/v1/execute", headers=HEADERS, json=body)
    assert result.status_code == 200
    assert result.json()["evidence"]["data_mode"] == mode
    assert result.json()["brief"]["verification_status"] == "review_required"
    assert result.headers["Cache-Control"] == "no-store"
    assert "X-Workshop-Code" in result.headers["Vary"]
    assert CODE not in result.text + response.text + entered.text + caplog.text
    # Successful entry does not grant access to a following request without the header.
    assert client.post("/api/v1/execute", json=body).status_code == 401


def test_legacy_contract_and_code_rotation(monkeypatch):
    response = client.post("/api/v1/analyze", json={"question": QUESTION}, headers=HEADERS)
    assert response.status_code == 200
    assert set(response.json()) == {"request_id", "question", "query_plan", "evidence", "brief"}
    replacement = "test-only-replacement-credential"
    monkeypatch.setattr(main.settings, "workshop_access_code", replacement)
    assert client.post("/api/v1/access", headers=HEADERS).status_code == 401
    response = client.post("/api/v1/access", headers={"X-Workshop-Code": replacement})
    assert response.status_code == 200


def test_url_body_and_cookie_are_not_access_credentials():
    response = client.post("/api/v1/access", params={"code": CODE}, json={"code": CODE},
                           headers={"Cookie": f"workshop_code={CODE}"})
    assert response.status_code == 401
    assert CODE not in response.text


@pytest.mark.asyncio
async def test_rejected_request_never_reads_body_or_calls_app():
    async def forbidden(*args):
        raise AssertionError("Body and application must remain untouched")
    messages = []

    async def send(message):
        messages.append(message)

    middleware = WorkshopAccessMiddleware(forbidden, lambda: main.settings)
    await middleware({"type": "http", "path": "/api/v1/execute", "method": "POST",
                      "headers": []}, forbidden, send)
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_static_surface_remains_public():
    calls = []

    async def static(scope, receive, send):
        calls.append(scope["path"])

    middleware = WorkshopAccessMiddleware(static, lambda: main.settings)
    for path in ("/", "/assets/app.js"):
        await middleware({"type": "http", "path": path}, None, None)
    assert calls == ["/", "/assets/app.js"]
