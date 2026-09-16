import pytest
from fastapi.testclient import TestClient

from newsroom_agent.main import app

client = TestClient(app)


def test_health_reports_mock_mode() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["public_data_mode"] == "mock"
    assert response.json()["live_api_enabled"] is False


def test_kosis_question_is_routed_and_requires_clarification() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?", "mode": "mock"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query_plan"]["selected_source"] == "kosis"
    assert payload["query_plan"]["clarification_required"] is True
    assert payload["evidence"]["data_mode"] == "mock"
    assert payload["brief"]["verification_status"] == "review_required"


def test_opendart_question_is_routed() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "삼성전자의 최근 실적은 악화됐는가?", "mode": "mock"},
    )
    assert response.status_code == 200
    assert response.json()["query_plan"]["selected_source"] == "opendart"


def test_live_mode_is_disabled_by_default() -> None:
    response = client.post(
        "/api/v1/analyze",
        json={"question": "청년 고용률을 알려줘", "mode": "live"},
    )
    assert response.status_code == 503


KOSIS_QUESTION = "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?"
OPENDART_QUESTION = "삼성전자의 최근 실적은 악화됐는가?"


def approved_request(source="kosis"):
    conditions = {
        "selected_source": source,
        "entity": "전국 시·도" if source == "kosis" else "삼성전자",
        "metric": "고용률" if source == "kosis" else "매출액",
        "period": "2020-2024",
        "comparison": "증감 폭",
        "filters": (
            {"age_range": "15-29세", "frequency": "연간"}
            if source == "kosis"
            else {"statement_basis": "연결", "report_type": "연간"}
        ),
    }
    return {
        "question": KOSIS_QUESTION if source == "kosis" else OPENDART_QUESTION,
        "mode": "mock",
        "approved": True,
        "conditions": conditions,
    }


def test_plan_only_interprets_without_generating_results(monkeypatch):
    from newsroom_agent.orchestrator import MockOrchestrator

    def forbidden(*args, **kwargs):
        raise AssertionError("Planning must not generate evidence or a briefing")

    monkeypatch.setattr(MockOrchestrator, "analyze", forbidden)
    monkeypatch.setattr(MockOrchestrator, "execute", forbidden)
    monkeypatch.setattr(MockOrchestrator, "_now", forbidden)
    for question, source in [(KOSIS_QUESTION, "kosis"), (OPENDART_QUESTION, "opendart")]:
        response = client.post("/api/v1/plan", json={"question": question, "mode": "mock"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["query_plan"]["selected_source"] == source
        assert payload["query_plan"]["clarification_required"] is True
        assert "metric" in payload["required_fields"]
        assert "period" in payload["required_fields"]
        assert "evidence" not in payload and "brief" not in payload
        assert "general_response" not in payload
        assert "calculation" not in payload
        assert payload["interpretation_method"] == "mock_rules"
        assert payload["available_years"] == (
            [2020, 2021, 2022, 2023, 2024] if source == "kosis" else []
        )


def test_undetermined_plan_explains_how_to_clarify():
    response = client.post("/api/v1/plan", json={"question": "무엇을 조사할까요?"})
    payload = response.json()
    assert payload["query_plan"]["selected_source"] == "undetermined"
    assert payload["required_fields"] == ["selected_source"]
    assert "질문을 구체화" in payload["query_plan"]["clarification_questions"][0]
    assert "evidence" not in payload


def test_explicit_conditions_can_be_approved_unchanged():
    question = "전국 시·도 청년 고용률 2020-2024 증감 폭 15-29세 연간 비교"
    plan = client.post("/api/v1/plan", json={"question": question}).json()
    assert plan["required_fields"] == []
    assert plan["query_plan"]["clarification_required"] is False
    conditions = {key: plan["query_plan"][key] for key in approved_request()["conditions"]}
    response = client.post(
        "/api/v1/execute",
        json={
            "question": question,
            "mode": "mock",
            "approved": True,
            "conditions": conditions,
        },
    )
    assert response.status_code == 200
    assert response.json()["query_plan"]["period"] == "2020-2024"


def test_multiple_metrics_are_not_silently_selected():
    plan = client.post(
        "/api/v1/plan",
        json={
            "question": "삼성전자 매출액과 영업이익 2020-2024 비교",
        },
    ).json()
    assert plan["query_plan"]["metric"] == ""
    assert "metric" in plan["required_fields"]


def test_explicit_quarter_is_not_silently_converted_to_annual():
    plan = client.post("/api/v1/plan", json={"question": "삼성전자의 최근 분기 실적"}).json()
    assert "filters.report_type" in plan["required_fields"]
    assert plan["query_plan"]["filters"]["report_type"] == ""


def test_nested_region_name_is_one_target():
    plan = client.post("/api/v1/plan", json={"question": "비수도권 시·도 청년 고용률"}).json()
    assert plan["query_plan"]["entity"] == "비수도권 시·도"


def test_separate_region_mentions_require_clarification():
    plan = client.post(
        "/api/v1/plan", json={"question": "비수도권 시·도와 수도권 시·도 청년 고용률"}
    ).json()
    assert plan["query_plan"]["entity"] == ""
    assert "entity" in plan["required_fields"]


def test_execution_requires_explicit_boolean_approval(monkeypatch):
    from newsroom_agent.orchestrator import MockOrchestrator

    def forbidden(*args, **kwargs):
        raise AssertionError("Unapproved requests must not execute")

    monkeypatch.setattr(MockOrchestrator, "execute", forbidden)
    for approval in [False, None, "true", 1, 0]:
        body = approved_request()
        body["approved"] = approval
        response = client.post("/api/v1/execute", json=body)
        assert response.status_code == 422
        assert "이 조건으로 조회" in response.json()["detail"]["field_errors"]["approved"]
    body = approved_request()
    del body["approved"]
    assert client.post("/api/v1/execute", json=body).status_code == 422


def test_approved_conditions_match_every_result_parameter():
    for source in ["kosis", "opendart"]:
        body = approved_request(source)
        response = client.post("/api/v1/execute", json=body)
        assert response.status_code == 200
        payload = response.json()
        for field, value in body["conditions"].items():
            assert payload["query_plan"][field] == value
            if field == "filters":
                for name, filter_value in value.items():
                    assert (
                        payload["evidence"]["query_parameters"][f"filters.{name}"] == filter_value
                    )
            else:
                assert payload["evidence"]["query_parameters"][field] == value
        assert payload["query_plan"]["clarification_required"] is False
        assert payload["query_plan"]["clarification_questions"] == []
        assert payload["evidence"]["data_mode"] == "mock"
        assert len(payload["evidence"]["raw_values"]) == (8 if source == "kosis" else 0)
        assert payload["evidence"]["retrieved_at"]
        assert payload["brief"]["verification_status"] == "review_required"


def test_edits_change_metadata_without_rerouting_to_default_conditions():
    body = approved_request()
    body["conditions"].update(
        {
            "entity": "수도권 시·도",
            "metric": "취업자 수",
            "period": "2021-2023",
            "comparison": "증감률",
            "filters": {"age_range": "15-34세", "frequency": "연간"},
        }
    )
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["query_plan"]["entity"] == "수도권 시·도"
    assert payload["query_plan"]["period"] == "2021-2023"
    assert payload["evidence"]["unit"] == "천 명"
    assert "× 100" in payload["evidence"]["formula"]
    assert "수도권 시·도" in payload["brief"]["summary"]
    assert "취업자 수" in payload["brief"]["summary"]


def test_rate_difference_and_relative_change_have_distinct_units():
    body = approved_request()
    difference = client.post("/api/v1/execute", json=body).json()
    body["conditions"]["comparison"] = "증감률"
    relative = client.post("/api/v1/execute", json=body).json()
    assert "%p" in difference["evidence"]["formula"]
    assert "결과 단위: %" in relative["evidence"]["formula"]
    assert "%p" not in relative["evidence"]["formula"]


def test_incomplete_and_unsupported_conditions_are_rejected():
    cases = [
        ("entity", ""),
        ("entity", "지원하지 않는 대상"),
        ("metric", "실적 악화 여부"),
        ("metric", "매출액"),
        ("comparison", "알아서 비교"),
        ("period", "최근 5년"),
        ("period", "2024-2020"),
        ("period", "2024-2024"),
        ("period", "1800-2024"),
        ("period", "2020-2200"),
        ("selected_source", "undetermined"),
    ]
    for field, value in cases:
        body = approved_request()
        body["conditions"][field] = value
        response = client.post("/api/v1/execute", json=body)
        assert response.status_code == 422
        assert field in response.json()["detail"]["field_errors"]
        assert "evidence" not in response.json()


def test_unresolved_or_unknown_filters_are_rejected():
    for filters, error_field in [
        ({"frequency": "연간"}, "filters.age_range"),
        ({"age_range": "15-29세", "frequency": "분기"}, "filters.frequency"),
        ({"age_range": "15-29세", "frequency": "연간", "other": "ignored?"}, "filters"),
    ]:
        body = approved_request()
        body["conditions"]["filters"] = filters
        response = client.post("/api/v1/execute", json=body)
        assert response.status_code == 422
        assert error_field in response.json()["detail"]["field_errors"]


def test_wrong_source_and_client_validation_flags_cannot_bypass_checks():
    body = approved_request("opendart")
    body["question"] = KOSIS_QUESTION
    assert client.post("/api/v1/execute", json=body).status_code == 422
    body = approved_request()
    body["conditions"]["clarification_required"] = False
    assert client.post("/api/v1/execute", json=body).status_code == 422


def test_new_endpoints_only_accept_mock_even_when_live_setting_is_enabled(monkeypatch):
    from newsroom_agent.main import settings

    monkeypatch.setattr(settings, "live_api_enabled", True)
    for mode in ["live", "snapshot"]:
        for endpoint in ["plan", "execute"]:
            body = approved_request() if endpoint == "execute" else {"question": KOSIS_QUESTION}
            body["mode"] = mode
            response = client.post(f"/api/v1/{endpoint}", json=body)
            assert response.status_code == 422
            assert "모의 자료 모드" in response.json()["detail"]["field_errors"]["mode"]


def test_blank_questions_and_malformed_requests_have_korean_errors():
    for question in ["   ", "가", "가" * 1001]:
        response = client.post("/api/v1/plan", json={"question": question})
        assert response.status_code == 422
        assert "질문을" in response.json()["detail"]["field_errors"]["question"]
    malformed = client.post(
        "/api/v1/execute", content="{", headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["message"] == "입력 내용을 확인해 주세요."


def test_new_execution_is_stateless_and_uses_new_conditions_each_time():
    body = approved_request("opendart")
    first = client.post("/api/v1/execute", json=body).json()
    body["conditions"]["metric"] = "영업이익"
    body["conditions"]["filters"]["statement_basis"] = "별도"
    second = client.post("/api/v1/execute", json=body).json()
    assert first["request_id"] != second["request_id"]
    assert first["query_plan"]["metric"] == "매출액"
    assert second["query_plan"]["metric"] == "영업이익"
    assert second["evidence"]["query_parameters"]["filters.statement_basis"] == "별도"


@pytest.mark.parametrize("source", ["kosis", "opendart"])
def test_approved_comparison_shares_question_and_labels_scripted_mock(source):
    body = approved_request(source)
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == body["question"]
    assert payload["general_response"]["text"]
    assert payload["general_response"]["data_mode"] == "mock"
    assert payload["general_response"]["generation_method"] == "scripted"
    assert payload["evidence"]["data_mode"] == "mock"
    assert len(payload["evidence"]["raw_values"]) == (8 if source == "kosis" else 0)
    assert payload["brief"]["verification_status"] == "review_required"


@pytest.mark.parametrize("source", ["kosis", "opendart"])
def test_reapproval_changes_grounded_conditions_but_keeps_authored_example(source):
    body = approved_request(source)
    first = client.post("/api/v1/execute", json=body).json()
    body["conditions"].update(
        {
            "period": "2021-2023",
            "metric": "취업자 수" if source == "kosis" else "영업이익",
            "comparison": "증감률",
        }
    )
    second = client.post("/api/v1/execute", json=body).json()
    assert first["question"] == second["question"]
    assert first["general_response"] == second["general_response"]
    assert first["brief"] != second["brief"]
    for field in ("period", "metric", "comparison"):
        assert second["query_plan"][field] == body["conditions"][field]
        assert second["evidence"]["query_parameters"][field] == body["conditions"][field]


def test_workshop_question_types_have_distinct_general_examples():
    employment = client.post("/api/v1/execute", json=approved_request()).json()
    financial = client.post("/api/v1/execute", json=approved_request("opendart")).json()
    assert employment["general_response"]["text"] != financial["general_response"]["text"]
    assert "고용" in employment["general_response"]["text"]
    assert "실적" in financial["general_response"]["text"]


def test_comparison_not_returned_for_unapproved_or_unresolved_conditions():
    unapproved = approved_request()
    unapproved["approved"] = False
    unresolved = approved_request()
    unresolved["conditions"]["metric"] = ""
    for body in (unapproved, unresolved):
        response = client.post("/api/v1/execute", json=body)
        assert response.status_code == 422
        assert set(response.json()) == {"detail"}


def test_legacy_analysis_response_keeps_its_original_fields():
    for question in (KOSIS_QUESTION, OPENDART_QUESTION, "무엇을 조사할까요?"):
        response = client.post("/api/v1/analyze", json={"question": question, "mode": "mock"})
        assert response.status_code == 200
        assert set(response.json()) == {"request_id", "question", "query_plan", "evidence", "brief"}


@pytest.mark.parametrize("failure", ["invalid_planner_output", "planner_unavailable"])
def test_planner_failure_is_safe_retryable_and_does_not_run_tools(monkeypatch, caplog, failure):
    from newsroom_agent.main import get_question_planner
    from newsroom_agent.orchestrator import MockOrchestrator
    from newsroom_agent.providers.planner import PlannerUnavailable

    class FailingPlanner:
        def interpret(self, question):
            if failure == "planner_unavailable":
                raise PlannerUnavailable("internal-adapter-detail")
            return "untrusted-adapter-output"

    def forbidden(*args, **kwargs):
        raise AssertionError("Planning must not execute or generate results")

    monkeypatch.setitem(app.dependency_overrides, get_question_planner, lambda: FailingPlanner())
    monkeypatch.setattr(MockOrchestrator, "execute", forbidden)
    monkeypatch.setattr(MockOrchestrator, "_now", forbidden)
    response = client.post("/api/v1/plan", json={"question": KOSIS_QUESTION})
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert response.json()["detail"]["code"] == failure
    assert response.json()["detail"]["field_errors"] == {}
    assert "질문 분석" in response.json()["detail"]["message"]
    for marker in ("internal-adapter-detail", "untrusted-adapter-output"):
        assert marker not in response.text and marker not in caplog.text
    monkeypatch.delitem(app.dependency_overrides, get_question_planner)
    retried = client.post("/api/v1/plan", json={"question": KOSIS_QUESTION})
    assert retried.status_code == 200
    assert "evidence" not in retried.json()


def test_execution_and_legacy_analysis_do_not_depend_on_planner(monkeypatch):
    from newsroom_agent.providers.mock_planner import MockQuestionPlanner

    def forbidden(*args, **kwargs):
        raise AssertionError("Approved execution and legacy analysis must not call a planner")

    monkeypatch.setattr(MockQuestionPlanner, "interpret", forbidden)
    assert client.post("/api/v1/execute", json=approved_request()).status_code == 200
    assert client.post("/api/v1/analyze", json={"question": KOSIS_QUESTION}).status_code == 200


def test_mixed_source_question_cannot_bypass_the_scope_guard_on_execution():
    body = approved_request()
    body["question"] = "삼성전자 매출액과 청년 고용률 지역 통계 비교"
    plan = client.post("/api/v1/plan", json={"question": body["question"]}).json()
    assert plan["query_plan"]["selected_source"] == "undetermined"
    assert "질문을 나누어" in plan["query_plan"]["selection_reason"]
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 422
    assert "selected_source" in response.json()["detail"]["field_errors"]


def test_synthetic_results_change_when_comparison_changes():
    body = approved_request()
    difference = client.post("/api/v1/execute", json=body).json()
    body["conditions"]["comparison"] = "증감률"
    relative = client.post("/api/v1/execute", json=body).json()
    assert difference["calculation"]["rows"][0]["region"] == "가상 지역 B"
    assert difference["calculation"]["rows"][0]["change"] == "9.00"
    assert difference["calculation"]["result_unit"] == "%p"
    assert relative["calculation"]["rows"][0]["region"] == "가상 지역 C"
    assert relative["calculation"]["rows"][0]["change"] == "23.33"
    assert relative["calculation"]["result_unit"] == "%"
    assert relative["general_response"] == difference["general_response"]
    assert relative["calculation"]["data_origin"] == "synthetic"
    assert "가상 자료" in relative["evidence"]["source_name"]
    assert "공식 통계 아님" in relative["evidence"]["table_or_report"]
    assert "가상" in relative["brief"]["summary"]


def test_raw_values_match_calculation_inputs_and_approved_conditions():
    body = approved_request()
    body["conditions"].update({"entity": "수도권 시·도", "period": "2021-2023"})
    result = client.post("/api/v1/execute", json=body).json()
    calculation = result["calculation"]
    assert calculation["start_year"] == 2021 and calculation["end_year"] == 2023
    assert {row["region"] for row in calculation["rows"]} == {"가상 지역 A", "가상 지역 B"}
    for row in calculation["rows"]:
        for year, key in [(2021, "start_value"), (2023, "end_value")]:
            raw = next(
                value
                for value in result["evidence"]["raw_values"]
                if value["region"] == row["region"] and value["year"] == year
            )
            assert raw["value"] == row[key]
            assert raw["unit"] == calculation["input_unit"]
            assert raw["metric"] == body["conditions"]["metric"]
            assert raw["age_range"] == body["conditions"]["filters"]["age_range"]
    assert result["evidence"]["query_parameters"]["entity"] == "수도권 시·도"
    assert result["evidence"]["query_parameters"]["period"] == "2021-2023"


def test_period_metric_and_age_select_different_series():
    body = approved_request()
    body["conditions"]["period"] = "2020-2021"
    short = client.post("/api/v1/execute", json=body).json()
    assert short["calculation"]["rows"][0]["region"] == "가상 지역 C"
    body["conditions"]["period"] = "2020-2024"
    body["conditions"]["filters"]["age_range"] = "15-34세"
    older = client.post("/api/v1/execute", json=body).json()
    assert [(row["region"], row["rank"]) for row in older["calculation"]["rows"]] == [
        ("가상 지역 A", 1),
        ("가상 지역 B", 2),
        ("가상 지역 C", 2),
        ("가상 지역 D", 4),
    ]
    body["conditions"]["filters"]["age_range"] = "15-29세"
    body["conditions"]["metric"] = "취업자 수"
    counts = client.post("/api/v1/execute", json=body).json()
    assert counts["calculation"]["input_unit"] == counts["calculation"]["result_unit"] == "천 명"
    assert counts["calculation"]["rows"][0]["change"] == "18.00"
    assert counts["calculation"]["rows"][-1]["change"] == "-4.00"


def test_missing_and_zero_values_are_not_fabricated_or_silently_dropped():
    body = approved_request()
    body["conditions"].update({"metric": "취업자 수", "comparison": "증감률"})
    body["conditions"]["filters"]["age_range"] = "15-34세"
    result = client.post("/api/v1/execute", json=body).json()
    rows = {row["region"]: row for row in result["calculation"]["rows"]}
    assert rows["가상 지역 A"]["status"] == "zero_baseline"
    assert rows["가상 지역 A"]["rank"] is None
    assert rows["가상 지역 B"]["change"] == "40.00"
    assert rows["가상 지역 C"]["status"] == "missing_value"
    assert rows["가상 지역 C"]["end_value"] is None
    assert len(result["evidence"]["raw_values"]) == 8
    assert "1곳" in result["brief"]["summary"]
    assert result["calculation"]["warnings"]
    body["conditions"]["entity"] = "비수도권 시·도"
    all_missing = client.post("/api/v1/execute", json=body).json()
    assert all(row["rank"] is None for row in all_missing["calculation"]["rows"])
    assert "순위를 제시할 수 없습니다" in all_missing["brief"]["summary"]
    assert "1위" not in all_missing["brief"]["summary"]


def test_workshop_recovery_changes_period_without_repairing_original_missing_values():
    body = approved_request()
    body["conditions"].update({"metric": "취업자 수", "comparison": "증감률"})
    body["conditions"]["filters"]["age_range"] = "15-34세"
    original = client.post("/api/v1/execute", json=body).json()
    assert [row["status"] for row in original["calculation"]["rows"]].count("calculated") == 1

    body["conditions"]["period"] = "2021-2023"
    response = client.post("/api/v1/execute", json=body)
    assert response.status_code == 200
    recovered = response.json()
    calculation = recovered["calculation"]
    assert len(calculation["rows"]) == 4
    assert all(row["status"] == "calculated" for row in calculation["rows"])
    assert calculation["warnings"] == []
    row_a = next(row for row in calculation["rows"] if row["region"] == "가상 지역 A")
    assert (row_a["start_value"], row_a["end_value"], row_a["change"]) == ("10", "14", "40.00")
    assert {value["year"] for value in recovered["evidence"]["raw_values"]} == {2021, 2023}
    assert recovered["evidence"]["query_parameters"]["period"] == "2021-2023"
    assert recovered["query_plan"]["period"] == "2021-2023"
    assert recovered["evidence"]["data_mode"] == "mock"
    assert recovered["brief"]["verification_status"] == "review_required"

    body["conditions"]["period"] = "2020-2024"
    repeated = client.post("/api/v1/execute", json=body).json()
    assert repeated["calculation"] == original["calculation"]
    assert repeated["evidence"]["raw_values"] == original["evidence"]["raw_values"]


def test_synthetic_period_is_bounded_without_changing_opendart_conditions():
    body = approved_request()
    body["conditions"]["period"] = "2019-2024"
    rejected = client.post("/api/v1/execute", json=body)
    assert rejected.status_code == 422
    assert "2020~2024" in rejected.json()["detail"]["field_errors"]["period"]
    body = approved_request("opendart")
    body["conditions"]["period"] = "2019-2024"
    unchanged = client.post("/api/v1/execute", json=body)
    assert unchanged.status_code == 200
    assert unchanged.json()["calculation"] is None
    assert unchanged.json()["evidence"]["raw_values"] == []


def test_invalid_synthetic_data_stops_with_clear_error(monkeypatch):
    from newsroom_agent import orchestrator
    from newsroom_agent.calculations import CalculationDataError

    def broken_dataset(*args, **kwargs):
        raise CalculationDataError("internal test detail")

    monkeypatch.setattr(orchestrator, "calculate_employment", broken_dataset)
    response = client.post("/api/v1/execute", json=approved_request())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "invalid_mock_data"
    assert "계산을 중단" in response.json()["detail"]["message"]
    assert "internal test detail" not in response.text
    assert set(response.json()) == {"detail"}
