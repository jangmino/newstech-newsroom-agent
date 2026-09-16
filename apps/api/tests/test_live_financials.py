"""Approved live contract tested offline with a public excerpt and mocked transport."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from newsroom_agent import main
from newsroom_agent.calculations import CalculationDataError, ValuePair, financial_change
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import ERROR_MESSAGES

FIXTURE = json.loads((Path(__file__).parents[1] / "src/newsroom_agent/snapshot_data/"
                     "opendart-samsung-revenue-2022-2024.json").read_text())
QUESTION = "삼성전자 2022-2024년 연결 연간 매출액 증감률 비교"
CONDITIONS = {
    "selected_source": "opendart", "entity": "삼성전자", "metric": "매출액",
    "period": "2022-2024", "comparison": "증감률",
    "filters": {"statement_basis": "연결", "report_type": "연간"},
}
api = TestClient(main.app)


def request_body():
    return {"question": QUESTION, "mode": "live", "approved": True,
            "conditions": {**CONDITIONS, "filters": dict(CONDITIONS["filters"])}}


def response_for(year):
    # Reconstruct only the selected row from the normalized excerpt, not a full API recording.
    row = next(row for row in FIXTURE["observations"] if str(row["year"]) == year)
    return {"status": "000", "list": [{
        "corp_code": row["corp_code"], "bsns_year": year, "reprt_code": row["report_code"],
        "account_id": row["account_id"], "account_nm": row["account_name"],
        "rcept_no": row["receipt_no"], "currency": row["currency"],
        "sj_div": row["statement_type"], "thstrm_amount": row["raw_amount"],
    }]}


@pytest.fixture
def live(monkeypatch):
    for key, value in {
        "live_api_enabled": True, "public_data_mode": "live", "opendart_enabled": True,
        "opendart_api_key": "offline-test-credential",
    }.items():
        monkeypatch.setattr(main.settings, key, value)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_for(request.url.params["bsns_year"]))

    monkeypatch.setattr(main, "OpenDartClient", lambda *args, **kwargs: OpenDartClient(
        "offline-test-credential", enabled=True, transport=httpx.MockTransport(handler),
    ))
    return calls


def test_live_plan_approval_and_exact_conditions(live):
    plan = api.post("/api/v1/plan", json={"question": QUESTION, "mode": "live"}).json()
    assert live == []
    assert plan["data_mode"] == "live" and plan["available_years"] == [2022, 2024]
    assert plan["field_options"]["metric"] == ["매출액"]
    assert plan["field_options"]["filters.statement_basis"] == ["연결"]
    assert not plan["query_plan"]["clarification_required"]
    assert not ({"evidence", "brief", "financial_calculation"} & plan.keys())
    body = request_body()
    body["conditions"]["comparison"] = "증감 폭"
    response = api.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    result = response.json()
    assert [call.url.params["bsns_year"] for call in live] == ["2022", "2024"]
    assert result["evidence"]["data_mode"] == "live"
    for key, value in body["conditions"].items():
        assert result["query_plan"][key] == value
        if key == "filters":
            for field, item in value.items():
                assert result["evidence"]["query_parameters"][f"filters.{field}"] == item
        else:
            assert result["evidence"]["query_parameters"][key] == value
    assert result["financial_calculation"]["change"] == "-1360457000000"
    assert result["financial_calculation"]["result_unit"] == "원"
    assert result["calculation"] is None
    assert result["brief"]["verification_status"] == "review_required"
    assert result["general_response"]["data_mode"] == "mock"
    for actual, expected in zip(
        result["evidence"]["raw_values"], FIXTURE["observations"], strict=True,
    ):
        assert actual["value"] == expected["amount"]
        assert actual["source_url"] == expected["verification"]["filing_url"]
        assert actual["retrieved_at"] != expected["retrieved_at"]  # fresh fetch, not fixture time
        assert actual["account_id"] == expected["account_id"]
    assert "offline-test-credential" not in response.text
    assert "crtfc_key" not in response.text


def test_live_relative_change_and_general_example(live):
    result = api.post("/api/v1/execute", json=request_body()).json()
    assert result["financial_calculation"]["change"] == "-0.45"
    assert result["financial_calculation"]["decimal_places"] == 2
    assert result["financial_calculation"]["result_unit"] == "%"
    assert "-0.45 %" in result["brief"]["summary"]
    assert len(live) == 2


@pytest.mark.parametrize("approved", [None, False, "true", 1])
def test_no_approval_never_calls_provider(live, approved):
    body = request_body()
    if approved is None:
        body.pop("approved")
    else:
        body["approved"] = approved
    assert api.post("/api/v1/execute", json=body).status_code == 422
    assert not live


@pytest.mark.parametrize("field,value", [
    ("entity", "다른 기업"), ("metric", "영업이익"), ("period", "2022-2023"),
    ("period", "2024-2022"), ("comparison", "순위"), ("selected_source", "kosis"),
    ("filters", {"statement_basis": "별도", "report_type": "연간"}),
    ("filters", {"statement_basis": "연결", "report_type": "분기"}),
    ("filters", {"statement_basis": "연결", "report_type": "연간", "extra": "x"}),
])
def test_unsupported_live_conditions_never_call_provider(live, field, value):
    body = request_body()
    body["conditions"][field] = value
    response = api.post("/api/v1/execute", json=body)
    assert response.status_code == 422 and not live
    assert response.json()["detail"]["code"] == "invalid_conditions"


def test_question_source_mismatch_never_calls_provider(live):
    body = request_body()
    body["question"] = "청년 고용률 비교"
    assert api.post("/api/v1/execute", json=body).status_code == 422
    assert not live


def test_unsupported_live_plan_values_are_cleared(live):
    response = api.post("/api/v1/plan", json={
        "question": "삼성전자 2020-2024 별도 영업이익 증감률 연간", "mode": "live",
    }).json()
    plan = response["query_plan"]
    assert plan["metric"] == plan["period"] == plan["filters"]["statement_basis"] == ""
    assert plan["clarification_required"] and len(plan["clarification_questions"]) >= 3
    assert not live


def test_opendart_activation_does_not_enable_kosis(live):
    response = api.post("/api/v1/plan", json={"question": "청년 고용률 비교", "mode": "live"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kosis_disabled"
    assert not live


@pytest.mark.parametrize("setting,value,code", [
    ("live_api_enabled", False, "disabled"), ("public_data_mode", "mock", "disabled"),
    ("opendart_enabled", False, "disabled"), ("opendart_api_key", "", "configuration"),
])
def test_each_server_gate_blocks_before_planning_or_fetch(live, monkeypatch, setting, value, code):
    monkeypatch.setattr(main.settings, setting, value)
    monkeypatch.setattr(main, "create_plan", lambda *args: pytest.fail("No model after gate"))
    for endpoint in ("plan", "execute"):
        body = request_body() if endpoint == "execute" else {"question": QUESTION, "mode": "live"}
        response = api.post(f"/api/v1/{endpoint}", json=body)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == f"opendart_{code}"
    assert not live


@pytest.mark.parametrize("code", list(ERROR_MESSAGES))
def test_provider_errors_are_safe_and_never_fall_back(live, monkeypatch, code):
    from newsroom_agent.providers.opendart_financials import OpenDartError

    async def fail(*args):
        raise OpenDartError(code)

    monkeypatch.setattr(OpenDartClient, "fetch_revenue", fail)
    response = api.post("/api/v1/execute", json=request_body())
    assert response.status_code == (429 if code == "rate_limited" else 503)
    assert response.json() == {"detail": {
        "code": f"opendart_{code}", "message": ERROR_MESSAGES[code], "field_errors": {},
    }}


def test_second_year_failure_has_no_partial_result(live, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_for("2022") if len(calls) == 1 else {
            "status": "013", "message": "offline-test-credential",
        })

    monkeypatch.setattr(main, "OpenDartClient", lambda *args, **kwargs: OpenDartClient(
        "offline-test-credential", enabled=True, transport=httpx.MockTransport(handler),
    ))
    response = api.post("/api/v1/execute", json=request_body())
    assert response.status_code == 503 and len(calls) == 2
    assert list(response.json()) == ["detail"]
    assert "offline-test-credential" not in response.text


def test_mock_and_legacy_never_call_live_even_when_enabled(live):
    body = request_body()
    body["mode"] = "mock"
    assert api.post("/api/v1/execute", json=body).json()["evidence"]["data_mode"] == "mock"
    legacy = api.post("/api/v1/analyze", json={"question": QUESTION}).json()
    assert "financial_calculation" not in legacy
    response = api.post("/api/v1/analyze", json={"question": QUESTION, "mode": "live"})
    assert response.status_code == 501
    assert not live


@pytest.mark.parametrize("start,end,comparison,change,status", [
    ("302231360000000", "300870903000000", "증감률", "-0.45", "calculated"),
    ("9007199254740993", "9007199254740994", "증감 폭", "1", "calculated"),
    ("999999999999999999999999999998", "999999999999999999999999999999",
     "증감 폭", "1", "calculated"),
    ("0", "3", "증감률", None, "zero_baseline"),
    ("0", "3", "증감 폭", "3", "calculated"),
    ("32", "33", "증감률", "3.13", "calculated"),
    ("100000", "99999", "증감률", "0.00", "calculated"),
])
def test_financial_arithmetic(start, end, comparison, change, status):
    result = financial_change(ValuePair("삼성전자", start, end, "원", "원"), 2022, 2024, comparison)
    assert result.change == change and result.status == status
    assert result.start_value == start and result.end_value == end


@pytest.mark.parametrize("start,end,unit", [
    (None, "1", "원"), ("", "1", "원"), ("NaN", "1", "원"), ("-1", "1", "원"),
    ("1.5", "2", "원"), ("1", "2", "백만원"), ("1" + "0" * 30, "2", "원"),
])
def test_invalid_financial_numbers_stop(start, end, unit):
    with pytest.raises(CalculationDataError):
        financial_change(ValuePair("삼성전자", start, end, "원", unit), 2022, 2024, "증감 폭")


def test_public_fixture_documented_unit_conversion():
    assert FIXTURE["fixture_kind"] == "normalized_public_excerpt"
    for row in FIXTURE["observations"]:
        original = row["verification"]
        assert original["original_unit"] == "백만원"
        assert Decimal(original["original_amount"]) * 1_000_000 == Decimal(row["amount"])
        assert original["matches_api"]
