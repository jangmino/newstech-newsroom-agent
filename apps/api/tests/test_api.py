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
        assert payload["evidence"]["raw_values"] == []
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
    assert payload["evidence"]["raw_values"] == []
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
