"""Approved, source-constrained OpenDART workflow; no model composition or fallback."""

from collections.abc import Callable
from uuid import uuid4

from newsroom_agent.calculations import ValuePair, financial_change
from newsroom_agent.conditions import (
    OPENDART_LIVE_REASON,
    SNAPSHOT_REASONS,
    calculation_metadata,
    route_question,
    validate_conditions,
)
from newsroom_agent.models import (
    Brief,
    CacheMetadata,
    Evidence,
    ExecutionResponse,
    GeneralResponseExample,
    QueryConditions,
    QueryPlan,
    SnapshotMetadata,
)
from newsroom_agent.orchestrator import GENERAL_RESPONSE_EXAMPLES, InvalidConditions
from newsroom_agent.providers.opendart import OpenDartClient
from newsroom_agent.providers.opendart_financials import (
    ANNUAL_REPORT_CODE,
    SAMSUNG_CORP_CODE,
    RevenuePair,
)
from newsroom_agent.public_data_cache import PublicDataCache


async def execute_financials(
    question: str, conditions: QueryConditions, client_factory: Callable[[], OpenDartClient],
    *, cache: PublicDataCache[RevenuePair] | None = None,
) -> ExecutionResponse:
    errors = validate_conditions(conditions, "live")
    if (conditions.selected_source != "opendart"
            or conditions.selected_source != route_question(question)):
        errors["selected_source"] = "자료원과 질문이 달라졌습니다. 질문을 다시 해석해 주세요."
    if errors:
        raise InvalidConditions(errors)
    start_year, end_year = map(int, conditions.period.split("-"))
    async def fetch():
        return await client_factory().fetch_revenue(start_year, end_year)

    cache_metadata = None
    if cache is None:
        pair = await fetch()
    else:
        pair, cache_metadata = await cache.get((
            ("contract", "opendart-revenue-v1"), ("corp_code", SAMSUNG_CORP_CODE),
            ("reprt_code", ANNUAL_REPORT_CODE), ("fs_div", "CFS"),
            ("start_year", str(start_year)), ("end_year", str(end_year)),
        ), fetch)
    return compose_financials(question, conditions, pair, cache=cache_metadata)


def compose_financials(
    question: str, conditions: QueryConditions, pair: RevenuePair, *,
    cache: CacheMetadata | None = None, snapshot: SnapshotMetadata | None = None,
) -> ExecutionResponse:
    start_year, end_year = map(int, conditions.period.split("-"))
    calculation = financial_change(ValuePair(
        region=conditions.entity, start_value=pair.start.amount, end_value=pair.end.amount,
        start_unit=pair.start.unit, end_unit=pair.end.unit,
    ), start_year, end_year, conditions.comparison)
    unit, formula = calculation_metadata(conditions)
    caveats = [
        *(snapshot.caveats if snapshot else []),
        *pair.caveats,
        "시작·종료 연도만 비교합니다. 중간 연도 추세나 기업 실적 전반을 판단할 수 없습니다.",
        "금액과 증감 폭은 원 단위 정수입니다. 증감률만 소수 둘째 자리까지 반올림해 표시합니다.",
        "공시 원문의 백만원 표기와 API의 원 단위를 구분해 대조해 주세요.",
    ]
    if calculation.reason:
        caveats.append(calculation.reason)
    change_text = (
        f"{calculation.change} {calculation.result_unit}입니다."
        if calculation.status == "calculated" else f"계산할 수 없습니다. {calculation.reason}"
    )
    return ExecutionResponse(
        request_id=str(uuid4()), question=question,
        query_plan=QueryPlan(**conditions.model_dump(), selection_reason=(
            SNAPSHOT_REASONS["opendart"] if snapshot else OPENDART_LIVE_REASON
        )),
        general_response=GeneralResponseExample(text=GENERAL_RESPONSE_EXAMPLES["opendart"]),
        financial_calculation=calculation,
        cache=cache, snapshot=snapshot,
        evidence=Evidence(
            source_name="OpenDART · 금융감독원 전자공시",
            table_or_report=(f"삼성전자 {start_year}·{end_year}년 사업보고서 "
                             "· 연결 손익계산서 매출액"),
            query_parameters={
                "selected_source": conditions.selected_source, "entity": conditions.entity,
                "metric": conditions.metric, "period": conditions.period,
                "comparison": conditions.comparison,
                **{f"filters.{key}": value for key, value in conditions.filters.items()},
            },
            retrieved_at=pair.end.retrieved_at.isoformat(), unit=unit, formula=formula,
            raw_values=[{
                "year": row.year, "value": row.amount, "raw_amount": row.raw_amount,
                "unit": row.unit, "currency": row.currency, "account_id": row.account_id,
                "account_name": row.account_name, "statement_type": row.statement_type,
                "receipt_no": row.receipt_no, "source_url": row.source_url,
                "retrieved_at": row.retrieved_at.isoformat(), **row.query_parameters,
            } for row in (pair.start, pair.end)],
            caveats=caveats, data_mode="snapshot" if snapshot else "live",
        ),
        brief=Brief(
            summary=("저장 자료 기준: " if snapshot else "")
                    + f"삼성전자 {start_year}→{end_year}년 연결 매출액의 {conditions.comparison}은 "
                    + change_text,
            verified_facts=[
                f"{row.year}년 사업보고서 당기 매출액: {int(row.amount):,} 원 "
                f"(접수번호 {row.receipt_no})." for row in (pair.start, pair.end)
            ] + [f"승인한 비교 기준: {conditions.comparison}. 계산 결과: {change_text}"],
            interpretation_limits=[
                "이 브리핑은 조회한 매출액과 코드 계산으로 구성했습니다. "
                "모델의 실적 평가가 아닙니다.",
                "매출액 두 시점만으로 수익성·성장 원인·실적 악화를 단정할 수 없습니다.",
                *caveats,
            ],
            follow_up_questions=[
                "공시 원문의 연결 기준·단위·정정 여부를 확인했는가?",
                "영업이익과 사업부별 변화 등 추가 취재가 필요한가?",
            ],
        ),
    )
