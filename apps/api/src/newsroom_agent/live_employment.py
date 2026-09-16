"""Approved KOSIS workflow: one source, deterministic calculation, human review required."""

from collections.abc import Callable
from uuid import uuid4

from newsroom_agent.calculations import ValuePair, rank_changes
from newsroom_agent.conditions import (
    KOSIS_LIVE_REASON,
    calculation_metadata,
    route_question,
    validate_conditions,
)
from newsroom_agent.models import (
    Brief,
    CalculationResult,
    Evidence,
    ExecutionResponse,
    GeneralResponseExample,
    QueryConditions,
    QueryPlan,
)
from newsroom_agent.orchestrator import GENERAL_RESPONSE_EXAMPLES, InvalidConditions
from newsroom_agent.providers.kosis import KosisClient
from newsroom_agent.providers.kosis_employment import TABLE_NAME, EmploymentQuery, EmploymentSeries
from newsroom_agent.public_data_cache import PublicDataCache


async def execute_employment(
    question: str, conditions: QueryConditions, client_factory: Callable[[], KosisClient],
    *, cache: PublicDataCache[EmploymentSeries] | None = None,
) -> ExecutionResponse:
    errors = validate_conditions(conditions, "live")
    if (conditions.selected_source != "kosis"
            or conditions.selected_source != route_question(question)):
        errors["selected_source"] = "자료원과 질문이 달라졌습니다. 질문을 다시 해석해 주세요."
    if errors:
        raise InvalidConditions(errors)
    start_year, end_year = map(int, conditions.period.split("-"))
    query = EmploymentQuery(
        entity=conditions.entity, metric=conditions.metric,
        age_range=conditions.filters["age_range"],
        start_year=start_year, end_year=end_year,
    )
    async def fetch():
        return await client_factory().fetch_employment(query)

    cache_metadata = None
    if cache is None:
        series = await fetch()
    else:
        series, cache_metadata = await cache.get(
            (("contract", "kosis-employment-v1"), *sorted(query.parameters.items())), fetch,
        )
    by_cell = {(row.region_code, row.year): row for row in series.observations}
    rows, warnings = rank_changes([
        ValuePair(
            region=by_cell[region, start_year].region_name,
            start_value=by_cell[region, start_year].value,
            end_value=by_cell[region, end_year].value,
            start_unit=by_cell[region, start_year].unit,
            end_unit=by_cell[region, end_year].unit,
        ) for region in query.region_codes
    ], "%", conditions.comparison, region_label="시도")
    unit, formula = calculation_metadata(conditions)
    result_unit = "%" if conditions.comparison == "증감률" else "%p"
    calculation = CalculationResult(
        dataset_id=f"kosis:{series.org_id}:{series.table_id}:{series.item_id}:{series.age_code}:annual",
        data_origin="kosis", start_year=start_year, end_year=end_year,
        input_unit=unit, result_unit=result_unit, rows=rows, warnings=warnings,
    )
    leaders = [row for row in rows if row.rank == 1]
    summary = (
        f"{conditions.entity}의 {start_year}→{end_year}년 15~29세 고용률을 비교했습니다. "
    )
    if leaders:
        summary += (
            f"{conditions.comparison}이 가장 큰 시도는 "
            + "·".join(row.region for row in leaders)
            + f"이며, 변화값은 {leaders[0].change} {result_unit}입니다."
        )
    else:
        summary += "계산 가능한 시도가 없어 순위를 매기지 않았습니다."
    caveats = [
        *series.caveats,
        "순위는 고용률 수준이 아니라 승인한 시작·종료 연도의 변화값을 비교한 결과입니다.",
        "연간 값의 비교입니다. 중간 연도 값은 근거에 남기지만 "
        "변화의 원인·추세를 단정하지 않습니다.",
        "증감 폭의 단위는 %p, 증감률의 단위는 %입니다. 표시값은 소수 둘째 자리로 반올림합니다.",
        "반올림 전 변화값으로 순위를 정합니다. "
        "순위 차이가 통계적으로 유의한 차이라는 뜻은 아닙니다.",
        "공표 고용률을 사용하며 취업자 수·15~34세 고용률·권역 전체 비율로 환산하지 않습니다.",
        *warnings,
    ]
    return ExecutionResponse(
        request_id=str(uuid4()), question=question,
        query_plan=QueryPlan(**conditions.model_dump(), selection_reason=KOSIS_LIVE_REASON),
        general_response=GeneralResponseExample(text=GENERAL_RESPONSE_EXAMPLES["kosis"]),
        calculation=calculation,
        cache=cache_metadata,
        evidence=Evidence(
            source_name="KOSIS · 국가데이터처 경제활동인구조사",
            table_or_report=f"{TABLE_NAME} · 15~29세 연간 고용률",
            query_parameters={
                "selected_source": conditions.selected_source, "entity": conditions.entity,
                "metric": conditions.metric, "period": conditions.period,
                "comparison": conditions.comparison,
                **{f"filters.{key}": value for key, value in conditions.filters.items()},
            },
            retrieved_at=series.retrieved_at.isoformat(), unit=unit, formula=formula,
            raw_values=[{
                "region": row.region_name, "region_code": row.region_code, "year": row.year,
                "value": row.value, "raw_value": row.raw_value, "unit": row.unit,
                "last_changed_at": row.last_changed_at.isoformat(),
                "retrieved_at": series.retrieved_at.isoformat(), "source_url": series.source_url,
                "org_id": series.org_id, "table_id": series.table_id, "item_id": series.item_id,
                "age_code": series.age_code, "period_code": row.period_code,
            } for row in series.observations],
            caveats=caveats, data_mode="live",
        ),
        brief=Brief(
            summary=summary,
            verified_facts=[
                f"{conditions.entity} {len(rows)}개 시도의 15~29세 연간 고용률(%)을 조회했습니다.",
                f"조회한 {len(series.observations)}개 셀의 "
                "표·연령·단위·연도·중복·누락을 검사했습니다.",
                f"비교 기간은 {start_year}~{end_year}년, "
                f"승인한 비교 기준은 {conditions.comparison}입니다.",
            ] + [
                f"{row.region}: {row.start_value}% → {row.end_value}%, "
                f"{conditions.comparison} {row.change} {result_unit}." for row in leaders
            ],
            interpretation_limits=[
                "이 브리핑은 공식 공표값과 코드 계산으로 구성했습니다. "
                "모델의 고용 상황 평가가 아닙니다.",
                "두 시점의 변화만으로 정책 효과나 고용의 질이 개선됐다고 단정할 수 없습니다.",
                *caveats,
            ],
            follow_up_questions=[
                "원표의 연령·지역 경계·최종수정일과 조사대상 정의를 확인했는가?",
                "표본오차와 지역별 인구구성 변화가 비교에 어떤 영향을 주는가?",
                "변화의 원인을 설명하려면 어떤 현장 취재와 추가 자료가 필요한가?",
            ],
        ),
    )
