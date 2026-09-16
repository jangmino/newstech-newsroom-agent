from datetime import UTC, datetime

from newsroom_agent.conditions import (
    KOSIS_HINTS,
    OPENDART_HINTS,
    SELECTION_REASONS,
    calculation_metadata,
    route_question,
    validate_conditions,
)
from newsroom_agent.models import (
    AnalysisResponse,
    Brief,
    Evidence,
    ExecutionResponse,
    GeneralResponseExample,
    PlanResponse,
    QueryConditions,
    QueryPlan,
    SourceName,
)
from newsroom_agent.planning import create_plan
from newsroom_agent.providers.mock_employment import calculate_employment
from newsroom_agent.providers.mock_planner import MockQuestionPlanner
from newsroom_agent.providers.planner import QuestionPlanner
from newsroom_agent.request_logging import request_id

# Authored workshop examples, not recorded model outputs or retrieved facts.
GENERAL_RESPONSE_EXAMPLES = {
    "kosis": (
        "청년 고용이 좋아진 지역을 살펴보려면 고용률과 취업자 수의 변화를 함께 볼 수 있습니다. "
        "지역별 산업구조와 청년 인구 변화도 해석에 영향을 줄 수 있습니다. "
        "어느 지역의 개선 폭이 가장 큰지는 같은 기간과 기준으로 자료를 비교해야 알 수 있습니다."
    ),
    "opendart": (
        "기업 실적을 판단하려면 매출과 영업이익의 흐름을 함께 살펴볼 수 있습니다. "
        "매출이 늘어도 비용이 더 크게 늘면 이익은 줄어들 수 있습니다. "
        "실적 악화 여부를 판단하려면 비교 기간과 재무제표 기준을 맞춰 확인해야 합니다."
    ),
}


class InvalidConditions(ValueError):
    def __init__(self, field_errors: dict[str, str]) -> None:
        super().__init__("조회 전에 확인이 필요한 조건이 있습니다.")
        self.field_errors = field_errors


class MockOrchestrator:
    """Mock-first orchestrator used until provider contracts are verified."""

    def __init__(self, planner: QuestionPlanner | None = None) -> None:
        self.planner = planner if planner is not None else MockQuestionPlanner()

    def plan(self, question: str) -> PlanResponse:
        return create_plan(question, self.planner)

    def execute(self, question: str, conditions: QueryConditions) -> ExecutionResponse:
        source = route_question(question)
        errors = validate_conditions(conditions)
        if conditions.selected_source != source:
            errors["selected_source"] = "자료원과 질문이 달라졌습니다. 질문을 다시 해석해 주세요."
        if errors:
            raise InvalidConditions(errors)

        unit, formula = calculation_metadata(conditions)
        query_plan = QueryPlan(
            **conditions.model_dump(),
            selection_reason=SELECTION_REASONS[source],
        )
        parameters = {
            "selected_source": conditions.selected_source,
            "entity": conditions.entity,
            "metric": conditions.metric,
            "period": conditions.period,
            "comparison": conditions.comparison,
            **{f"filters.{key}": value for key, value in conditions.filters.items()},
        }
        response = ExecutionResponse(
            request_id=request_id(),
            question=question,
            query_plan=query_plan,
            general_response=GeneralResponseExample(
                text=GENERAL_RESPONSE_EXAMPLES[conditions.selected_source]
            ),
            evidence=Evidence(
                source_name="KOSIS" if conditions.selected_source == "kosis" else "OpenDART",
                table_or_report="승인 조건에 따른 모의 자료 — 실제 연결 전",
                query_parameters=parameters,
                retrieved_at=self._now(),
                unit=unit,
                raw_values=[],
                formula=formula,
                caveats=[
                    "실제 공공데이터를 조회하지 않았으며 원자료 숫자와 계산 결과가 없습니다.",
                    "표시된 단위와 계산식은 승인 조건에 따른 모의 조회 설계입니다.",
                    "시각은 실제 조회 시점이 아닌 모의 자료 생성 시각입니다.",
                    "증감률은 시작 연도 값이 0이면 계산할 수 없습니다.",
                ],
                data_mode="mock",
            ),
            brief=Brief(
                summary=(f"{conditions.entity}의 {conditions.metric} 비교 조건을 확인했습니다."),
                verified_facts=[
                    f"참가자가 승인한 조건: {label} — {value}"
                    for label, value in [
                        ("대상", conditions.entity),
                        ("지표", conditions.metric),
                        ("기간", conditions.period),
                        ("비교 기준", conditions.comparison),
                    ]
                ],
                interpretation_limits=[
                    "조건 승인은 결과의 검증 완료를 뜻하지 않습니다.",
                    "원자료를 조회하지 않았으므로 지역 순위나 실적 변화는 단정할 수 없습니다.",
                ],
                follow_up_questions=[
                    "선택한 대상과 지표가 취재 질문에 적합한가?",
                    "원자료의 정의·단위와 비교 기간의 일관성을 확인했는가?",
                ],
            ),
        )
        if conditions.selected_source == "kosis":
            self._add_employment_calculation(response, conditions)
        return response

    @staticmethod
    def _add_employment_calculation(
        response: ExecutionResponse,
        conditions: QueryConditions,
    ) -> None:
        calculation = calculate_employment(conditions)
        response.calculation = calculation
        evidence = response.evidence
        evidence.source_name = "워크숍 가상 자료 (KOSIS 연동 준비)"
        evidence.table_or_report = (
            f"가상 청년 고용 예제 · {calculation.dataset_id} · 공식 통계 아님"
        )
        evidence.raw_values = [
            {
                "region": row.region,
                "year": year,
                "value": value,
                "metric": conditions.metric,
                "age_range": conditions.filters["age_range"],
                "unit": calculation.input_unit,
            }
            for row in calculation.rows
            for year, value in (
                (calculation.start_year, row.start_value),
                (calculation.end_year, row.end_value),
            )
        ]
        evidence.caveats = [
            "지역과 숫자는 직접 만든 가상 자료입니다. KOSIS 공식 통계나 실제 지역 순위가 아닙니다.",
            "전국은 가상 지역 A~D, 수도권은 A·B, 비수도권은 C·D를 선택하는 실습 분류입니다.",
            "시작·종료 연도만 비교하며 중간 연도의 추세를 요약하지 않습니다.",
            "표시값은 소수 둘째 자리로 반올림합니다. 순위는 반올림 전 값으로 정합니다.",
            "시각은 가상 자료를 불러와 계산한 시각이며 공식 자료 조회 시각이 아닙니다.",
            *calculation.warnings,
        ]
        winners = [row for row in calculation.rows if row.rank == 1]
        valid_count = sum(row.status == "calculated" for row in calculation.rows)
        if winners:
            names = ", ".join(row.region for row in winners)
            rank_label = "공동 1위" if len(winners) > 1 else "1위"
            response.brief.summary = (
                f"{conditions.entity} 실습 범위의 계산 가능한 가상 지역 "
                f"{valid_count}곳 중 {names}: "
                f"{conditions.metric} {conditions.comparison} {rank_label}입니다."
            )
            response.brief.verified_facts.extend(
                f"가상 계산 · {row.region}: {row.start_value} → {row.end_value} "
                f"{calculation.input_unit}, 변화 {row.change} {calculation.result_unit}"
                for row in winners
            )
        else:
            response.brief.summary = (
                f"{conditions.entity} 실습 범위의 모든 가상 지역이 계산 불가하여 "
                "순위를 제시할 수 없습니다."
            )
        response.brief.interpretation_limits = [
            "가상 숫자의 계산 결과로 실제 지역의 고용 상황이나 정책 효과를 판단할 수 없습니다.",
            "순위는 변화값의 내림차순이며, 1위라도 값이 감소했을 수 있습니다.",
            "조건 승인과 계산 완료는 기사에 사용할 수 있다는 검증을 뜻하지 않습니다.",
            *calculation.warnings,
        ]

    def analyze(self, question: str) -> AnalysisResponse:
        source = self._route(question)
        if source == "kosis":
            return self._kosis_response(question)
        if source == "opendart":
            return self._opendart_response(question)
        return self._undetermined_response(question)

    @staticmethod
    def _route(question: str) -> SourceName:
        kosis_score = sum(hint in question for hint in KOSIS_HINTS)
        opendart_score = sum(hint in question for hint in OPENDART_HINTS)
        if kosis_score > opendart_score:
            return "kosis"
        if opendart_score > kosis_score:
            return "opendart"
        return "undetermined"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _kosis_response(self, question: str) -> AnalysisResponse:
        return AnalysisResponse(
            request_id=request_id(),
            question=question,
            query_plan=QueryPlan(
                selected_source="kosis",
                selection_reason=(
                    "지역·청년·고용 지표를 묻는 질문이므로 국가통계포털 자료가 적합합니다."
                ),
                entity="전국 시·도",
                metric="청년 고용 개선",
                period="최근 5년",
                comparison="시작 연도와 종료 연도 비교",
                filters={"frequency": "annual"},
                clarification_required=True,
                clarification_questions=[
                    "청년의 연령 범위를 어떻게 정의할까요?",
                    "취업자 수와 고용률 중 어느 지표를 사용할까요?",
                    "증감 폭과 증감률 중 어떤 기준으로 순위를 정할까요?",
                ],
            ),
            evidence=Evidence(
                source_name="KOSIS",
                table_or_report="실습용 예시 통계표 — 실제 연결 전",
                query_parameters={"period": "5Y", "region": "all"},
                retrieved_at=self._now(),
                unit="% 또는 천 명 — 지표 확인 필요",
                raw_values=[],
                formula="종료 시점 값 - 시작 시점 값",
                caveats=[
                    "현재는 모의 자료 모드입니다.",
                    "청년과 개선의 정의가 확정되지 않았습니다.",
                ],
                data_mode="mock",
            ),
            brief=Brief(
                summary="지표 정의를 확정하기 전에는 지역 순위를 단정할 수 없습니다.",
                verified_facts=["질문의 성격에 따라 KOSIS가 자료원으로 선택됐습니다."],
                interpretation_limits=["연령 범위와 지표에 따라 결과가 달라질 수 있습니다."],
                follow_up_questions=[
                    "정책 대상 연령과 통계상 청년 정의가 같은가?",
                    "지역별 산업구조 차이가 결과에 영향을 주었는가?",
                ],
            ),
        )

    def _opendart_response(self, question: str) -> AnalysisResponse:
        return AnalysisResponse(
            request_id=request_id(),
            question=question,
            query_plan=QueryPlan(
                selected_source="opendart",
                selection_reason=(
                    "기업 실적과 재무제표를 묻는 질문이므로 전자공시 자료가 적합합니다."
                ),
                entity="삼성전자",
                metric="실적 악화 여부",
                period="최근 공시 기준",
                comparison="전년 동기 비교",
                filters={},
                clarification_required=True,
                clarification_questions=[
                    "연결재무제표와 별도재무제표 중 어느 기준을 사용할까요?",
                    "매출액과 영업이익 중 무엇을 핵심 지표로 볼까요?",
                    "연간과 분기 중 어느 기간을 비교할까요?",
                ],
            ),
            evidence=Evidence(
                source_name="OpenDART",
                table_or_report="실습용 예시 공시 — 실제 연결 전",
                query_parameters={"corp_name": "삼성전자"},
                retrieved_at=self._now(),
                unit="원 — 공시 단위 확인 필요",
                raw_values=[],
                formula="(당기 값 - 전기 값) / 전기 값 × 100",
                caveats=[
                    "현재는 모의 자료 모드입니다.",
                    "공시 유형과 재무제표 기준이 확정되지 않았습니다.",
                ],
                data_mode="mock",
            ),
            brief=Brief(
                summary="비교 기준을 확정하기 전에는 실적 악화를 단정할 수 없습니다.",
                verified_facts=["질문의 성격에 따라 OpenDART가 자료원으로 선택됐습니다."],
                interpretation_limits=[
                    "연결·별도 및 누계·분기 선택에 따라 변화율이 달라질 수 있습니다."
                ],
                follow_up_questions=[
                    "정정공시가 있었는가?",
                    "일회성 손익이 변화에 영향을 주었는가?",
                ],
            ),
        )

    def _undetermined_response(self, question: str) -> AnalysisResponse:
        return AnalysisResponse(
            request_id=request_id(),
            question=question,
            query_plan=QueryPlan(
                selected_source="undetermined",
                selection_reason=(
                    "질문만으로 기업공시와 국가통계 중 적합한 자료원을 결정하기 어렵습니다."
                ),
                clarification_required=True,
                clarification_questions=[
                    "특정 기업의 공시를 찾으시나요, 국가·지역 통계를 찾으시나요?"
                ],
            ),
            evidence=Evidence(
                source_name="선택 전",
                table_or_report="자료 조회 전",
                retrieved_at=self._now(),
                unit="확인 필요",
                formula="해당 없음",
                caveats=["자료원을 정하기 전에는 조회하지 않습니다."],
                data_mode="mock",
            ),
            brief=Brief(
                summary="자료원을 선택할 수 있도록 질문을 구체화해 주세요.",
                verified_facts=[],
                interpretation_limits=["현재 질문에는 데이터 대상을 식별할 정보가 부족합니다."],
                follow_up_questions=["조사하려는 대상과 기간은 무엇인가?"],
            ),
        )
