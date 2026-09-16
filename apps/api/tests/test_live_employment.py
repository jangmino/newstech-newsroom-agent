"""Approved KOSIS API flow using public data and offline transports only."""

import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.models import QueryConditions
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import ERROR_MESSAGES, KosisError

FIXTURE = json.loads((Path(__file__).parents[3] / "fixtures/public-data/"
                     "kosis-youth-employment-2020-2024.json").read_text())
QUESTION = "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교"
CONDITIONS = {
    "selected_source": "kosis", "entity": "전국 시·도", "metric": "고용률",
    "period": "2020-2024", "comparison": "증감 폭",
    "filters": {"age_range": "15-29세", "frequency": "연간"},
}
api = TestClient(main.app)


def body():
    return {"question": QUESTION, "mode": "live", "approved": True,
            "conditions": copy.deepcopy(CONDITIONS)}


@pytest.fixture
def live(monkeypatch):
    for name, value in {
        "live_api_enabled": True, "public_data_mode": "live", "kosis_enabled": True,
        "kosis_api_key": "offline-kosis-key", "opendart_enabled": False,
    }.items():
        monkeypatch.setattr(main.settings, name, value)
    calls = []

    def handler(request):
        calls.append(request)
        params = request.url.params
        return httpx.Response(200, json=[row for row in FIXTURE["rows"]
            if row["C1"] in params["objL1"].split("+")
            and params["startPrdDe"] <= row["PRD_DE"] <= params["endPrdDe"]])

    monkeypatch.setattr(main, "KosisClient", lambda *args, **kwargs: KosisClient(
        "offline-kosis-key", enabled=True, transport=httpx.MockTransport(handler),
    ))
    monkeypatch.setattr(main, "OpenDartClient", lambda *args, **kwargs: pytest.fail("No OpenDART"))
    return calls


def test_plan_without_data_then_approved_actual_source_and_auditable_results(live):
    plan = api.post("/api/v1/plan", json={"question": QUESTION, "mode": "live"}).json()
    assert not live
    assert plan["data_mode"] == "live" and plan["available_years"] == [2020, 2021, 2022, 2023, 2024]
    assert plan["field_options"]["metric"] == ["고용률"]
    assert plan["field_options"]["filters.age_range"] == ["15-29세"]
    assert not plan["query_plan"]["clarification_required"]
    assert not ({"evidence", "calculation", "brief"} & plan.keys())
    response = api.post("/api/v1/execute", json=body())
    assert response.status_code == 200
    result = response.json()
    assert len(live) == 1
    assert result["financial_calculation"] is None
    assert result["calculation"]["data_origin"] == "kosis"
    assert result["evidence"]["data_mode"] == "live"
    assert result["general_response"]["data_mode"] == "mock"
    assert result["brief"]["verification_status"] == "review_required"
    assert result["calculation"]["result_unit"] == "%p"
    leader = result["calculation"]["rows"][0]
    assert (leader["region"], leader["change"], leader["rank"]) == ("강원특별자치도", "7.30", 1)
    assert "강원특별자치도" in result["brief"]["summary"]
    assert "7.30 %p" in result["brief"]["summary"]
    assert len(result["evidence"]["raw_values"]) == 85
    for raw, stored in zip(result["evidence"]["raw_values"], FIXTURE["rows"], strict=True):
        assert raw["raw_value"] == stored["DT"] and raw["value"] == stored["DT"]
        assert raw["unit"] == "%" and raw["region_code"] == stored["C1"]
        assert raw["last_changed_at"] == stored["LST_CHN_DE"]
        assert raw["retrieved_at"] == result["evidence"]["retrieved_at"] != FIXTURE["retrieved_at"]
        assert raw["source_url"] == FIXTURE["source_url"]
    for field, value in CONDITIONS.items():
        assert result["query_plan"][field] == value
        if field == "filters":
            for key, item in value.items():
                assert result["evidence"]["query_parameters"][f"filters.{key}"] == item
        else:
            assert result["evidence"]["query_parameters"][field] == value
    assert "가상" not in json.dumps(result["calculation"], ensure_ascii=False)
    assert "offline-kosis-key" not in response.text and "apiKey" not in response.text


def test_edited_region_period_and_comparison_are_used_without_reinterpreting(live, monkeypatch):
    monkeypatch.setattr(main, "create_plan", lambda *args: pytest.fail("No model at execution"))
    request = body()
    request["conditions"].update(entity="수도권 시·도", period="2021-2023", comparison="증감률")
    response = api.post("/api/v1/execute", json=request)
    assert response.status_code == 200
    result = response.json()
    assert dict(live[0].url.params)["objL1"] == "11+23+31"
    assert live[0].url.params["startPrdDe"] == "2021"
    assert live[0].url.params["endPrdDe"] == "2023"
    assert len(result["evidence"]["raw_values"]) == 9
    assert len(result["calculation"]["rows"]) == 3
    assert result["calculation"]["result_unit"] == "%"
    assert result["query_plan"]["entity"] == "수도권 시·도"
    assert result["evidence"]["query_parameters"]["period"] == "2021-2023"
    assert {row["region"] for row in result["calculation"]["rows"]} == {
        "서울특별시", "인천광역시", "경기도",
    }


@pytest.mark.parametrize("approved", [None, False, "true", 1])
def test_approval_required_before_kosis_transport(live, approved):
    request = body()
    if approved is None:
        request.pop("approved")
    else:
        request["approved"] = approved
    assert api.post("/api/v1/execute", json=request).status_code == 422
    assert not live


@pytest.mark.parametrize("field,value", [
    ("metric", "취업자 수"), ("metric", "경제활동참가율"), ("entity", "전국"),
    ("period", "2019-2024"), ("period", "2020-2025"), ("period", "2024-2024"),
    ("comparison", "순위"), ("selected_source", "opendart"),
    ("filters", {"age_range": "15-34세", "frequency": "연간"}),
    ("filters", {"age_range": "15-29세", "frequency": "분기"}),
    ("filters", {"age_range": "15-29세", "frequency": "연간", "sex": "남자"}),
])
def test_unsupported_approved_conditions_fail_before_network(live, field, value):
    request = body()
    request["conditions"][field] = value
    response = api.post("/api/v1/execute", json=request)
    assert response.status_code == 422 and not live
    assert response.json()["detail"]["code"] == "invalid_conditions"


def test_source_mismatch_and_two_source_question_never_fetch(live):
    for question in ("삼성전자 매출액", "청년 고용과 삼성전자 매출 비교"):
        request = body()
        request["question"] = question
        assert api.post("/api/v1/execute", json=request).status_code == 422
        assert not live
    plan = api.post("/api/v1/plan", json={
        "question": "청년 고용과 삼성전자 매출 비교", "mode": "live",
    }).json()
    assert plan["query_plan"]["selected_source"] == "undetermined"
    assert plan["query_plan"]["clarification_required"] and not live


def test_unsupported_interpretation_is_cleared_without_substituting_supported_values(live):
    plan = api.post("/api/v1/plan", json={
        "question": "전국 시·도 15-34세 청년 취업자 수 2018-2024년 증감률 분기 비교",
        "mode": "live",
    }).json()
    assert plan["query_plan"]["metric"] == plan["query_plan"]["period"] == ""
    assert plan["query_plan"]["filters"] == {"age_range": "", "frequency": ""}
    assert plan["query_plan"]["clarification_required"] and len(plan["required_fields"]) == 4
    assert not live


@pytest.mark.parametrize("setting,value,code", [
    ("live_api_enabled", False, "disabled"), ("public_data_mode", "mock", "disabled"),
    ("kosis_enabled", False, "disabled"), ("kosis_api_key", "", "configuration"),
])
def test_each_kosis_gate_blocks_model_and_data(live, monkeypatch, setting, value, code):
    monkeypatch.setattr(main.settings, setting, value)
    monkeypatch.setattr(main, "create_plan", lambda *args: pytest.fail("No model after gate"))
    for endpoint in ("plan", "execute"):
        request = body() if endpoint == "execute" else {"question": QUESTION, "mode": "live"}
        response = api.post(f"/api/v1/{endpoint}", json=request)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == f"kosis_{code}"
    assert not live


def test_health_and_opendart_gate_remain_independent(live):
    health = api.get("/health").json()
    assert health["kosis_enabled"] and not health["opendart_enabled"]
    assert "offline-kosis-key" not in json.dumps(health)
    response = api.post("/api/v1/plan", json={"question": "삼성전자 매출액 비교", "mode": "live"})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "opendart_disabled"
    assert not live


@pytest.mark.parametrize("code", list(ERROR_MESSAGES))
def test_all_provider_errors_have_korean_envelopes_and_no_partial_result(live, monkeypatch, code):
    async def fail(*args):
        raise KosisError(code)

    monkeypatch.setattr(KosisClient, "fetch_employment", fail)
    response = api.post("/api/v1/execute", json=body())
    assert response.status_code == (429 if code == "rate_limited" else 503)
    assert response.json() == {"detail": {
        "code": f"kosis_{code}", "message": ERROR_MESSAGES[code], "field_errors": {},
    }}


@pytest.mark.parametrize("all_zero", [False, True])
def test_zero_baseline_has_no_invalid_rank_or_synthetic_warning(live, monkeypatch, all_zero):
    rows = copy.deepcopy(FIXTURE["rows"])
    for row in rows:
        if row["PRD_DE"] == "2020" and (all_zero or row["C1"] == "11"):
            row["DT"] = "0"
    monkeypatch.setattr(main, "KosisClient", lambda *args, **kwargs: KosisClient(
        "offline", enabled=True, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=rows)),
    ))
    request = body()
    request["conditions"]["comparison"] = "증감률"
    result = api.post("/api/v1/execute", json=request).json()
    calc = result["calculation"]
    seoul = next(row for row in calc["rows"] if row["region"] == "서울특별시")
    assert seoul["status"] == "zero_baseline" and seoul["rank"] is None
    assert calc["warnings"] and "가상" not in " ".join(calc["warnings"])
    if all_zero:
        assert "순위를 매기지 않았습니다" in result["brief"]["summary"]
        assert all(row["rank"] is None for row in calc["rows"])


def test_mock_and_legacy_never_fetch_live(live):
    request = body()
    request["mode"] = "mock"
    result = api.post("/api/v1/execute", json=request).json()
    assert result["evidence"]["data_mode"] == "mock"
    assert result["calculation"]["data_origin"] == "synthetic"
    assert api.post("/api/v1/analyze", json={"question": QUESTION}).status_code == 200
    legacy_live = api.post("/api/v1/analyze", json={"question": QUESTION, "mode": "live"})
    assert legacy_live.status_code == 501
    assert not live


@pytest.mark.asyncio
async def test_direct_financial_workflow_rejects_valid_kosis_conditions():
    from newsroom_agent.live_financials import execute_financials
    from newsroom_agent.orchestrator import InvalidConditions

    with pytest.raises(InvalidConditions):
        await execute_financials(QUESTION, QueryConditions(**CONDITIONS),
                                 lambda: pytest.fail("Wrong provider must not be constructed"))
