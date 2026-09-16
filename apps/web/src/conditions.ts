import type { PlanResponse, QueryConditions, QueryPlan, SourceName } from "./types";

export const conditionLabels: Record<string, string> = {
  selected_source: "자료원",
  entity: "대상",
  metric: "지표",
  period: "기간",
  comparison: "비교 기준",
  "filters.age_range": "청년 연령 범위",
  "filters.frequency": "통계 주기",
  "filters.statement_basis": "재무제표 기준",
  "filters.report_type": "공시 기간 기준",
};

export function sourceLabel(source: SourceName): string {
  return { kosis: "KOSIS", opendart: "OpenDART", undetermined: "자료원 확인 필요" }[source];
}

export function editableConditions(plan: QueryPlan): QueryConditions {
  return {
    selected_source: plan.selected_source,
    entity: plan.entity ?? "",
    metric: plan.metric ?? "",
    period: plan.period ?? "",
    comparison: plan.comparison ?? "",
    filters: { ...plan.filters },
  };
}

export function conditionValue(conditions: QueryConditions, field: string): string {
  if (field.startsWith("filters.")) return conditions.filters[field.slice(8)] ?? "";
  return conditions[field as keyof Omit<QueryConditions, "filters">];
}

export function updateCondition(
  conditions: QueryConditions, field: string, value: string,
): QueryConditions {
  if (field.startsWith("filters.")) {
    return { ...conditions, filters: { ...conditions.filters, [field.slice(8)]: value } };
  }
  return { ...conditions, [field]: value };
}

export function conditionErrors(plan: PlanResponse, conditions: QueryConditions): string[] {
  if (conditions.selected_source === "undetermined") {
    return ["기업공시 또는 청년 고용 통계 중 무엇을 알아보려는지 질문을 구체화해 주세요."];
  }
  if (!Object.keys(plan.field_options).length) {
    return ["지원하는 조회 조건을 확인하지 못했습니다. 질문을 다시 분석해 주세요."];
  }
  const errors = Object.entries(plan.field_options)
    .filter(([field, options]) => !options.includes(conditionValue(conditions, field)))
    .map(([field]) => `${conditionLabels[field] ?? field} 항목을 선택해 주세요.`);
  const period = /^(\d{4})-(\d{4})$/.exec(conditions.period.trim());
  if (!period || !(1900 <= Number(period[1]) && Number(period[1]) < Number(period[2]) && Number(period[2]) <= 2100)) {
    errors.push("기간을 시작 연도-종료 연도로 입력해 주세요. 예: 2020-2024.");
  } else if (plan.available_years?.length && (!plan.available_years.includes(Number(period[1])) || !plan.available_years.includes(Number(period[2])))) {
    const label = plan.data_mode === "snapshot" ? "저장된" : plan.data_mode === "live" ? "실제" : "가상";
    errors.push(plan.data_mode !== "mock" && conditions.selected_source === "opendart"
      ? `${label} 매출액 실습은 원문을 대조한 2022-2024년 비교만 지원합니다.`
      : `${label} 청년 고용 자료는 ${plan.available_years[0]}~${plan.available_years[plan.available_years.length - 1]}년만 지원합니다. 기간을 수정해 주세요.`);
  }
  return errors;
}
