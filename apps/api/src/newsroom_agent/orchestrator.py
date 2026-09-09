from datetime import UTC, datetime
from uuid import uuid4

from newsroom_agent.models import AnalysisResponse, Brief, Evidence, QueryPlan

KOSIS_HINTS = ("고용", "실업", "인구", "물가", "지역", "청년", "통계")
OPENDART_HINTS = ("기업", "회사", "매출", "영업이익", "당기순이익", "공시", "실적", "삼성전자")


class MockOrchestrator:
    """Mock-first orchestrator used until provider contracts are verified."""

    def analyze(self, question: str) -> AnalysisResponse:
        source = self._route(question)
        if source == "kosis":
            return self._kosis_response(question)
        if source == "opendart":
            return self._opendart_response(question)
        return self._undetermined_response(question)

    @staticmethod
    def _route(question: str) -> str:
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
            request_id=str(uuid4()),
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
            request_id=str(uuid4()),
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
            request_id=str(uuid4()),
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
