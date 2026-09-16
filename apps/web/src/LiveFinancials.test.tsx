import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import { editableConditions } from "./conditions";
import { canCompareResults } from "./resultComparison";
import { formatAmount } from "./FinancialEvidence";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, ExecutionResponse, PlanResponse } from "./types";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function livePlan(): PlanResponse {
  const plan = examplePlan("opendart");
  plan.data_mode = "live";
  plan.available_years = [2022, 2024];
  plan.query_plan.period = "2022-2024";
  plan.field_options.metric = ["매출액"];
  plan.field_options["filters.statement_basis"] = ["연결"];
  return plan;
}

function liveResult(request: ExecuteRequest): ExecutionResponse {
  const result = exampleResult(livePlan(), request.conditions);
  const relative = request.conditions.comparison === "증감률";
  result.evidence.data_mode = "live";
  result.evidence.table_or_report = "삼성전자 사업보고서 연결 매출액";
  result.evidence.caveats = ["공시 원문과 정정 여부를 확인해 주세요."];
  // Small, synthetic numbers for UI tests; never presented as a verified fixture.
  result.evidence.raw_values = [2022, 2024].map((year) => ({
    year, value: year === 2022 ? "100" : "120", raw_amount: year === 2022 ? "100" : "120",
    receipt_no: `2025010100${year}`, retrieved_at: "2026-09-16T00:00:00Z",
    account_id: "ifrs-full_Revenue", account_name: "매출액", statement_type: "IS",
    corp_code: "00126380", bsns_year: String(year), reprt_code: "11011", fs_div: "CFS", currency: "KRW",
  }));
  result.brief.summary = "승인한 연결 매출액의 변화입니다.";
  result.brief.interpretation_limits = ["매출액만으로 실적 전반을 단정할 수 없습니다."];
  result.financial_calculation = {
    data_origin: "opendart", start_year: 2022, end_year: 2024, start_value: "100", end_value: "120",
    input_unit: "원", result_unit: relative ? "%" : "원", change: relative ? "20.00" : "20",
    decimal_places: relative ? 2 : 0, status: "calculated", reason: null,
  };
  return result;
}

function setup() {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") return json(livePlan());
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(path).toBe("/api/v1/execute");
    expect(request.mode).toBe("live");
    expect(request.approved).toBe(true);
    return json(liveResult(request));
  });
  render(<App />);
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "live" } });
  fireEvent.click(screen.getByRole("button", { name: "삼성전자의 최근 실적은 악화됐는가?" }));
  return fetch;
}

async function plan() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("button", { name: "이 조건으로 조회" });
}

async function approve() {
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  return await screen.findByRole("region", { name: "이 결과의 실습 검토" });
}

test("live selection and planning never reveal evidence; approval uses edited conditions", async () => {
  const fetch = setup();
  expect(fetch).not.toHaveBeenCalled();
  await plan();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).mode).toBe("live");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("link", { name: /사업보고서/ })).toBeNull();
  expect(screen.queryByRole("option", { name: "영업이익" })).toBeNull();
  expect(screen.queryByRole("option", { name: "별도" })).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.getByText("참가자가 조건을 수정했습니다.", { exact: false })).toBeTruthy();
  await approve();
  const evidence = screen.getByRole("region", { name: "공시 원자료와 계산 결과" });
  expect(within(evidence).getByText("계산 결과: 20.00 %")).toBeTruthy();
  expect(within(evidence).getAllByRole("link")).toHaveLength(2);
  expect(within(evidence).getByRole("link", { name: /2022년 사업보고서/ }).getAttribute("href"))
    .toBe("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250101002022");
  expect(screen.getByText("승인한 조건으로 실제 조회했습니다.", { exact: false })).toBeTruthy();
  expect(screen.getByText("자료 조회 완료 시각")).toBeTruthy();
  expect(screen.queryByText("모의 자료 생성 시각")).toBeNull();
  expect(screen.queryByText("두 응답 모두 실습용 모의 예시입니다.", { exact: false })).toBeNull();
  const request = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  expect(request.conditions.comparison).toBe("증감률");
  expect(request.conditions.period).toBe("2022-2024");
  expect(screen.getByText("모의 예시 · 미리 작성한 응답")).toBeTruthy();
  expect(screen.getByText("공시 원문·접수번호·연도별 실제 조회 시각을 확인했습니다.")).toBeTruthy();
});

test("unsupported live period blocks approval with Korean guidance", async () => {
  const fetch = setup();
  await plan();
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2022-2023" } });
  expect(screen.getByText(/실제 매출액 실습은 원문을 대조한/)).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("KOSIS in live mode cannot be approved", async () => {
  const fetch = setup();
  fetch.mockResolvedValueOnce(json({ ...examplePlan(), data_mode: "live", field_options: {} }));
  await plan();
  expect(screen.getByText(/기업 질문으로 바꾸거나 모의 자료를 선택/)).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
});

test("live condition edit hides results; reapproval resets review and compares financial units", async () => {
  setup();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getByRole("checkbox", { name: "자료의 출처와 시각" }));
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.queryByRole("region", { name: "공시 원자료와 계산 결과" })).toBeNull();
  const next = await approve();
  expect(within(next).getByRole("status").textContent).toBe("실습 검토 전 · 0/4개 확인");
  expect(screen.getByRole("heading", { name: "조건 변경 전후 비교" })).toBeTruthy();
  expect(screen.getByText(/원 단위 증감 폭과 % 증감률은 서로 다른 값/)).toBeTruthy();
  expect(screen.queryByText(/원자료 숫자와 계산 결과가 없어 수치 변화는 비교하지 않습니다/)).toBeNull();
});

test("changing data mode clears plan, result, comparison and review without a request", async () => {
  const fetch = setup();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "mock" } });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
});

test("late live response cannot reappear after data mode changes", async () => {
  const fetch = setup();
  await plan();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect(screen.getByRole("button", { name: "공시 자료를 조회하는 중…" })).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "mock" } });
  await act(async () => finish(json(liveResult({ question: "삼성전자", mode: "live", approved: true,
    conditions: editableConditions(livePlan().query_plan) }))));
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
});

test("provider error keeps conditions, hides old evidence and does not silently retry", async () => {
  const fetch = setup();
  await plan();
  await approve();
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "opendart_timeout", message: "OpenDART 응답 시간이 초과됐습니다.", field_errors: {},
  } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("응답 시간이 초과");
  expect(screen.queryByRole("region", { name: "공시 원자료와 계산 결과" })).toBeNull();
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2022-2024");
  expect(fetch).toHaveBeenCalledTimes(3);
  await approve();
  expect(screen.getByText("실습 검토 전 · 0/4개 확인", { selector: "p" })).toBeTruthy();
});

test("a mock result is rejected for approved live conditions", async () => {
  const fetch = setup();
  await plan();
  fetch.mockResolvedValueOnce(json(exampleResult(livePlan(), editableConditions(livePlan().query_plan))));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("자료 모드를 확인하지 못했습니다");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
});

test("zero baseline shows inability to calculate instead of a fabricated rate", async () => {
  const fetch = setup();
  await plan();
  const result = liveResult({ question: "삼성전자", mode: "live", approved: true,
    conditions: editableConditions(livePlan().query_plan) });
  result.financial_calculation = { ...result.financial_calculation!, start_value: "0",
    status: "zero_baseline", change: null, reason: "시작 값이 0이므로 증감률을 계산할 수 없습니다." };
  fetch.mockResolvedValueOnce(json(result));
  await approve();
  expect(screen.getByText("시작 값이 0이므로 증감률을 계산할 수 없습니다.")).toBeTruthy();
});

test("exact amount formatting and result mode comparison", () => {
  expect(formatAmount("9007199254740993")).toBe("9,007,199,254,740,993");
  expect(formatAmount("-1360457000000")).toBe("-1,360,457,000,000");
  expect(formatAmount("-0.45")).toBe("-0.45");
  const plan = livePlan();
  const before = exampleResult(plan, editableConditions(plan.query_plan));
  const after = liveResult({ question: before.question, mode: "live", approved: true,
    conditions: { ...editableConditions(plan.query_plan), comparison: "증감률" } });
  expect(canCompareResults(before, after)).toBe(false);
});
