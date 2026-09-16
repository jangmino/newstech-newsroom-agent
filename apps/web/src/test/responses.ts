import type { ExecutionResponse, PlanResponse, QueryConditions } from "../types";

// Authored public mock responses; no provider responses or credentials are used.
export function examplePlan(source: "kosis" | "opendart" = "kosis"): PlanResponse {
  const employment = source === "kosis";
  return {
    request_id: "plan-example",
    interpretation_method: "mock_rules",
    interpretation_model: null,
    question: employment ? "전국 청년 고용률 비교" : "삼성전자 매출액 비교",
    query_plan: {
      selected_source: source, selection_reason: "실습용 자료원 선택",
      entity: employment ? "전국 시·도" : "삼성전자",
      metric: employment ? "고용률" : "매출액",
      period: "2020-2024", comparison: "증감 폭",
      filters: employment ? { age_range: "15-29세", frequency: "연간" }
        : { statement_basis: "연결", report_type: "연간" },
      clarification_required: false, clarification_questions: [],
    },
    required_fields: [],
    field_options: employment ? {
      entity: ["전국 시·도", "수도권 시·도", "비수도권 시·도"],
      metric: ["고용률", "취업자 수"], comparison: ["증감 폭", "증감률"],
      "filters.age_range": ["15-29세", "15-34세"], "filters.frequency": ["연간"],
    } : {
      entity: ["삼성전자"], metric: ["매출액", "영업이익"], comparison: ["증감 폭", "증감률"],
      "filters.statement_basis": ["연결", "별도"], "filters.report_type": ["연간"],
    },
    available_years: employment ? [2020, 2021, 2022, 2023, 2024] : [],
  };
}

export function exampleResult(plan: PlanResponse, conditions: QueryConditions): ExecutionResponse {
  const employment = conditions.selected_source === "kosis";
  return {
    // Deliberately reused: the UI must reset even on re-querying the same result ID.
    request_id: "result-example", question: plan.question,
    query_plan: { ...plan.query_plan, ...conditions },
    evidence: {
      source_name: employment ? "워크숍 가상 자료" : "OpenDART",
      table_or_report: "실습용 모의 자료 · 공식 조회 전",
      query_parameters: {
        selected_source: conditions.selected_source, entity: conditions.entity,
        metric: conditions.metric, period: conditions.period, comparison: conditions.comparison,
      },
      retrieved_at: "2026-09-16T00:00:00Z", unit: employment ? "%" : "원", raw_values: [],
      formula: "종료 값 - 시작 값", caveats: ["공식 자료를 조회하지 않았습니다."], data_mode: "mock",
    },
    brief: {
      summary: "조건에 따른 모의 브리핑입니다.", verified_facts: ["승인된 조회 조건을 확인했습니다."],
      interpretation_limits: ["실제 취재 근거로 사용할 수 없습니다."],
      follow_up_questions: ["원자료를 추가로 확인했는가?"], verification_status: "review_required",
    },
    general_response: { text: "미리 작성한 응답 예시입니다.", data_mode: "mock", generation_method: "scripted" },
    calculation: employment ? {
      dataset_id: "synthetic-test", data_origin: "synthetic", start_year: 2020, end_year: 2024,
      input_unit: "%", result_unit: "%p", decimal_places: 2, ranking_method: "변화값 내림차순",
      rows: [{ region: "가상 지역 A", start_value: "40", end_value: "48", change: "8.00",
        rank: 1, status: "calculated", reason: null }], warnings: [],
    } : null,
  };
}
