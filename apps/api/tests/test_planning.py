import json

import pytest

from newsroom_agent.models import QueryConditions
from newsroom_agent.orchestrator import MockOrchestrator
from newsroom_agent.planning import (
    MAX_OUTPUT_LENGTH,
    InvalidPlannerOutput,
    StructuredQuestion,
    create_plan,
    parse_interpretation,
)
from newsroom_agent.providers.mock_planner import MockQuestionPlanner

QUESTION = "전국 시·도 청년 고용률 2020-2024 증감 폭 15-29세 연간 비교"


def candidate():
    return {
        "selected_source": "kosis", "entity": "전국 시·도", "metric": "고용률",
        "period": "2020-2024", "comparison": "증감 폭",
        "filters": {"age_range": "15-29세", "frequency": "연간"}, "uncertain_fields": [],
    }


class StubPlanner:
    def __init__(self, output):
        self.raw = json.dumps(output, ensure_ascii=False)
        self.questions = []

    def interpret(self, question):
        self.questions.append(question)
        return self.raw


def test_contract_requires_all_keys_and_forbids_execution_fields():
    schema = StructuredQuestion.model_json_schema()
    assert set(schema["required"]) == set(candidate())
    assert schema["additionalProperties"] is False
    for key in candidate():
        output = candidate()
        del output[key]
        with pytest.raises(InvalidPlannerOutput):
            parse_interpretation(json.dumps(output))


@pytest.mark.parametrize("raw", [
    "", "not json", "```json\n{}\n```", "{} trailing", "null", "[]", "true", "0",
    json.dumps(candidate()).replace(
        '"selected_source": "kosis"', '"selected_source": "kosis", "selected_source": "kosis"',
    ),
    json.dumps(candidate(), ensure_ascii=False).replace(
        '"age_range": "15-29세"', '"age_range": "15-29세", "age_range": "15-29세"',
    ),
    '{"entity":NaN}', json.dumps(candidate()) + " " * MAX_OUTPUT_LENGTH, b"{}", None,
])
def test_malformed_oversized_or_duplicate_json_is_rejected_without_echo(raw):
    with pytest.raises(InvalidPlannerOutput) as error:
        parse_interpretation(raw)
    assert str(error.value) == ""


@pytest.mark.parametrize(("field", "value"), [
    ("selected_source", "web"), ("selected_source", ["kosis", "opendart"]),
    ("entity", 123), ("metric", ["고용률", "취업자 수"]), ("period", True),
    ("comparison", "x" * 101), ("filters", {"frequency": 1}),
    ("filters", {"frequency": {"value": "연간"}}),
    ("uncertain_fields", "metric"), ("uncertain_fields", ["approval"]),
    ("approved", True), ("clarification_required", False), ("brief", {"summary": "완료"}),
    ("tool_calls", [{"name": "execute"}]), ("selection_reason", "model-authored-reason"),
])
def test_wrong_types_and_authority_fields_cannot_enter_a_plan(field, value):
    output = candidate()
    output[field] = value
    with pytest.raises(InvalidPlannerOutput):
        create_plan(QUESTION, StubPlanner(output))


@pytest.mark.parametrize(("field", "value"), [
    ("entity", "지원하지 않는 지역"), ("metric", "매출액"), ("comparison", "자동 선택"),
    ("period", "최근 5년"), ("period", "2019-2024"), ("period", "2024-2020"),
    ("filters.age_range", "20-39세"), ("filters.frequency", "분기"),
])
def test_unsupported_values_are_cleared_and_return_korean_clarification(field, value):
    output = candidate()
    if field.startswith("filters."):
        output["filters"][field[8:]] = value
    else:
        output[field] = value
    result = create_plan(QUESTION, StubPlanner(output))
    assert result.required_fields == [field]
    assert result.query_plan.clarification_required is True
    assert result.query_plan.clarification_questions
    assert value not in result.query_plan.clarification_questions[0]
    dumped = result.query_plan.model_dump()
    assert (dumped["filters"][field[8:]] if field.startswith("filters.") else dumped[field]) == ""
    assert "evidence" not in result.model_dump() and "brief" not in result.model_dump()


def test_nulls_and_missing_filter_values_require_participant_choices():
    output = candidate()
    output.update(
        entity=None, metric=None, period=None, comparison=None, filters={"frequency": None},
    )
    result = create_plan(QUESTION, StubPlanner(output))
    assert set(result.required_fields) == {
        "entity", "metric", "period", "comparison", "filters.age_range", "filters.frequency",
    }
    assert set(result.query_plan.filters.values()) == {""}


def test_uncertainty_overrides_supported_values():
    output = candidate()
    output["uncertain_fields"] = ["metric", "period", "filters.age_range"]
    result = create_plan(QUESTION, StubPlanner(output))
    assert set(result.required_fields) == {"metric", "period", "filters.age_range"}
    assert result.query_plan.entity == "전국 시·도"
    assert result.query_plan.metric == result.query_plan.period == ""
    assert result.query_plan.filters["age_range"] == ""


def test_uncertain_source_discards_other_proposals_and_requests_question_edit():
    output = candidate()
    output["uncertain_fields"] = ["selected_source"]
    result = create_plan(QUESTION, StubPlanner(output))
    assert result.required_fields == ["selected_source"]
    assert result.query_plan.selected_source == "undetermined"
    assert result.query_plan.entity == result.query_plan.metric == result.query_plan.period == ""
    assert result.query_plan.filters == {}
    assert result.field_options == {} and result.available_years == []


@pytest.mark.parametrize("change", [
    {"selected_source": "opendart"},
    {"filters": {"age_range": "15-29세", "frequency": "연간", "statement_basis": "연결"}},
    {"uncertain_fields": ["filters.report_type"]},
])
def test_contradictory_source_or_foreign_filters_are_rejected(change):
    output = candidate() | change
    with pytest.raises(InvalidPlannerOutput):
        create_plan(QUESTION, StubPlanner(output))


def test_approved_execution_does_not_reinterpret_or_replace_edited_conditions():
    provider = StubPlanner(candidate())
    orchestrator = MockOrchestrator(provider)
    plan = orchestrator.plan(QUESTION)
    conditions = QueryConditions(
        **{key: getattr(plan.query_plan, key) for key in QueryConditions.model_fields}
    )
    conditions.metric = "취업자 수"
    conditions.period = "2021-2023"
    provider.raw = "A second interpretation must never be requested"
    result = orchestrator.execute(QUESTION, conditions)
    assert provider.questions == [QUESTION]
    assert result.query_plan.metric == "취업자 수"
    assert result.query_plan.period == "2021-2023"
    assert result.brief.verification_status == "review_required"


def test_valid_mock_output_uses_shared_validation_and_marks_its_method():
    result = create_plan(QUESTION, MockQuestionPlanner())
    assert result.interpretation_method == "mock_rules"
    assert result.required_fields == []
    assert result.query_plan.clarification_required is False
    assert result.query_plan.metric == "고용률"
    assert result.query_plan.filters == {"age_range": "15-29세", "frequency": "연간"}


def test_mixed_sources_do_not_choose_by_keyword_majority():
    result = create_plan("삼성전자 매출액과 청년 고용률 지역 통계를 비교", MockQuestionPlanner())
    assert result.query_plan.selected_source == "undetermined"
    assert result.required_fields == ["selected_source"]
    assert "질문을 나누어" in result.query_plan.selection_reason


def test_multiple_periods_stay_unresolved():
    result = create_plan(QUESTION + " 또는 2021-2023", MockQuestionPlanner())
    assert result.query_plan.period == ""
    assert result.required_fields == ["period"]
