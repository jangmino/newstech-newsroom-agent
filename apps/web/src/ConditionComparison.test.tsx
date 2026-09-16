import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { ConditionComparison } from "./ConditionComparison";
import { editableConditions } from "./conditions";
import { canCompareResults, comparisonConditions } from "./resultComparison";
import { examplePlan, exampleResult } from "./test/responses";

function results() {
  const plan = examplePlan();
  const previous = exampleResult(plan, editableConditions(plan.query_plan));
  const current = structuredClone(previous);
  current.query_plan.comparison = "증감률";
  return { previous, current };
}

test("each side keeps its own ranks, units, inputs and source metadata", () => {
  const { previous, current } = results();
  previous.calculation!.rows = [
    { region: "가상 지역 B", start_value: "50", end_value: "59", change: "9.00", rank: 1, status: "calculated", reason: null },
    { region: "가상 지역 C", start_value: "30", end_value: "37", change: "7.00", rank: 2, status: "calculated", reason: null },
  ];
  current.calculation!.result_unit = "%";
  current.calculation!.rows = [
    { region: "가상 지역 C", start_value: "30", end_value: "37", change: "23.33", rank: 1, status: "calculated", reason: null },
    { region: "가상 지역 B", start_value: "50", end_value: "59", change: "18.00", rank: 2, status: "calculated", reason: null },
  ];
  current.evidence.formula = "(종료 값 - 시작 값) / 시작 값 × 100";
  current.evidence.retrieved_at = "2026-09-16T01:00:00Z";
  render(<ConditionComparison previous={previous} current={current} />);
  const table = screen.getByRole("table", { name: "가상 지역별 결과 비교 · 공식 통계 아님" });
  const row = within(table).getByRole("row", { name: /가상 지역 C/ });
  const cells = within(row).getAllByRole("cell");
  expect(cells[0].textContent).toContain("2위 · 7.00 %p");
  expect(cells[1].textContent).toContain("1위 · 23.33 %");
  expect(cells[0].textContent).toContain("2020년: 30 % → 2024년: 37 %");
  for (const [title, result] of [["이전 승인 결과", previous], ["이번 승인 결과", current]] as const) {
    const card = screen.getByRole("article", { name: title });
    expect(card.textContent).toContain(result.evidence.formula);
    expect(card.textContent).toContain(new Date(result.evidence.retrieved_at).toLocaleString("ko-KR"));
    expect(card.textContent).toContain(result.evidence.caveats[0]);
  }
  expect(screen.getByText(/기준이 다른 값은 그대로 대소 비교할 수 없습니다/)).toBeTruthy();
});

test("out-of-scope, missing and zero-baseline rows remain distinct with warnings", () => {
  const { previous, current } = results();
  current.query_plan.entity = "비수도권 시·도";
  current.calculation!.rows = [
    { region: "가상 지역 C", start_value: "30", end_value: null, change: null, rank: null, status: "missing_value", reason: "종료 값이 없습니다." },
    { region: "가상 지역 D", start_value: "0", end_value: "2", change: null, rank: null, status: "zero_baseline", reason: "시작 값이 0입니다." },
  ];
  current.calculation!.warnings = ["계산 가능한 지역이 없어 순위를 매기지 않았습니다."];
  render(<ConditionComparison previous={previous} current={current} />);
  const table = screen.getByRole("table", { name: /가상 지역별 결과 비교/ });
  const a = within(table).getByRole("row", { name: /가상 지역 A/ });
  expect(within(a).getAllByRole("cell")[1].textContent).toBe("조회 대상에 포함되지 않음");
  const c = within(table).getByRole("row", { name: /가상 지역 C/ });
  expect(within(c).getAllByRole("cell")[0].textContent).toBe("조회 대상에 포함되지 않음");
  expect(within(c).getAllByRole("cell")[1].textContent).toContain("값 없음");
  const d = within(table).getByRole("row", { name: /가상 지역 D/ });
  expect(within(d).getAllByRole("cell")[1].textContent).toContain("2020년: 0 %");
  expect(within(table).getAllByText("계산 불가 · 순위 없음")).toHaveLength(2);
  expect(screen.getByText(current.calculation!.warnings[0])).toBeTruthy();
});

test("ties and rounded display values do not cause the browser to recalculate ranks", () => {
  const { previous, current } = results();
  current.calculation!.rows = [
    { region: "가상 지역 A", start_value: "1", end_value: "1.0011", change: "0.00", rank: 3, status: "calculated", reason: null },
    { region: "가상 지역 B", start_value: "1", end_value: "1.0012", change: "0.00", rank: 1, status: "calculated", reason: null },
    { region: "가상 지역 C", start_value: "1", end_value: "1.0012", change: "0.00", rank: 1, status: "calculated", reason: null },
  ];
  render(<ConditionComparison previous={previous} current={current} />);
  const table = screen.getByRole("table", { name: /가상 지역별 결과 비교/ });
  expect(within(table).getAllByText("1위 · 0.00 %p")).toHaveLength(2);
  expect(within(table).getByText("3위 · 0.00 %p")).toBeTruthy();
});

test("comparison ignores filter insertion order and request metadata, but includes removed filters", () => {
  const { previous, current } = results();
  current.query_plan.comparison = previous.query_plan.comparison;
  current.request_id = "different-id";
  current.query_plan.selection_reason = "새 설명";
  current.query_plan.filters = { frequency: "연간", age_range: "15-29세" };
  expect(canCompareResults(previous, current)).toBe(false);
  delete current.query_plan.filters.age_range;
  const age = comparisonConditions(previous.query_plan, current.query_plan).find((row) => row.field === "filters.age_range");
  expect(age).toMatchObject({ before: "15-29세", after: "없음", changed: true });
  expect(canCompareResults(previous, current)).toBe(true);
});

test("different questions or sources cannot be compared even if their conditions differ", () => {
  const { previous, current } = results();
  current.question = "다른 청년 고용 질문";
  expect(canCompareResults(previous, current)).toBe(false);
  current.question = previous.question;
  current.query_plan.selected_source = "opendart";
  expect(canCompareResults(previous, current)).toBe(false);
});
