"""Supported mock workshop conditions; no providers or data retrieval."""

import re

from newsroom_agent.models import QueryConditions, SourceName
from newsroom_agent.providers.mock_employment import YEARS

FIELD_LABELS = {
    "entity": "대상",
    "metric": "지표",
    "period": "기간",
    "comparison": "비교 기준",
    "filters.age_range": "청년 연령 범위",
    "filters.frequency": "통계 주기",
    "filters.statement_basis": "재무제표 기준",
    "filters.report_type": "공시 기간 기준",
}

FIELD_OPTIONS = {
    "kosis": {
        "entity": ["전국 시·도", "수도권 시·도", "비수도권 시·도"],
        "metric": ["고용률", "취업자 수"],
        "comparison": ["증감 폭", "증감률"],
        "filters.age_range": ["15-29세", "15-34세"],
        "filters.frequency": ["연간"],
    },
    "opendart": {
        "entity": ["삼성전자"],
        "metric": ["매출액", "영업이익"],
        "comparison": ["증감 폭", "증감률"],
        "filters.statement_basis": ["연결", "별도"],
        "filters.report_type": ["연간"],
    },
}

KOSIS_HINTS = ("고용", "실업", "인구", "물가", "지역", "청년", "통계")
OPENDART_HINTS = ("기업", "회사", "매출", "영업이익", "당기순이익", "공시", "실적", "삼성전자")
SELECTION_REASONS = {
    "kosis": (
        "청년 고용 통계의 조회 대상으로 KOSIS를 선택했습니다. "
        "이번 계산은 가상 자료를 사용합니다."
    ),
    "opendart": "기업 실적은 OpenDART에서 확인합니다. 모의 실습은 삼성전자를 다룹니다.",
    "undetermined": (
        "기업공시와 국가통계 중 적합한 자료원을 정하기 어렵습니다. "
        "두 자료원이 함께 언급됐다면 질문을 나누어 주세요."
    ),
}


def route_question(question: str) -> SourceName:
    """Deterministic scope guard for the two mock workshop question families."""
    kosis = any(hint in question for hint in KOSIS_HINTS)
    opendart = any(hint in question for hint in OPENDART_HINTS)
    if kosis and not opendart:
        return "kosis"
    if opendart and not kosis:
        return "opendart"
    return "undetermined"


def validate_conditions(conditions: QueryConditions) -> dict[str, str]:
    options = FIELD_OPTIONS.get(conditions.selected_source)
    if options is None:
        return {"selected_source": "자료원을 정할 수 있도록 질문을 구체화해 주세요."}

    errors = {}
    for field, choices in options.items():
        value = (
            conditions.filters.get(field.removeprefix("filters."), "")
            if field.startswith("filters.")
            else getattr(conditions, field)
        )
        if value not in choices:
            errors[field] = f"{FIELD_LABELS[field]} 항목을 선택해 주세요: {', '.join(choices)}."

    period = re.fullmatch(r"([0-9]{4})-([0-9]{4})", conditions.period)
    if period is None or not 1900 <= int(period[1]) < int(period[2]) <= 2100:
        errors["period"] = "기간을 시작 연도-종료 연도로 입력해 주세요. 예: 2020-2024."
    elif conditions.selected_source == "kosis" and any(
        int(year) not in YEARS for year in period.groups()
    ):
        errors["period"] = "가상 청년 고용 자료는 2020~2024년만 지원합니다. 기간을 수정해 주세요."

    allowed_filters = {
        key.removeprefix("filters.") for key in options if key.startswith("filters.")
    }
    if conditions.filters.keys() - allowed_filters:
        errors["filters"] = "이 자료원에서 지원하지 않는 추가 조건이 있습니다. 다시 해석해 주세요."
    return errors


def calculation_metadata(conditions: QueryConditions) -> tuple[str, str]:
    unit = {"고용률": "%", "취업자 수": "천 명", "매출액": "원", "영업이익": "원"}[
        conditions.metric
    ]
    if conditions.comparison == "증감률":
        return unit, "(종료 연도 값 - 시작 연도 값) / 시작 연도 값 × 100 (결과 단위: %)"
    result_unit = "%p" if conditions.metric == "고용률" else unit
    return unit, f"종료 연도 값 - 시작 연도 값 (결과 단위: {result_unit})"
