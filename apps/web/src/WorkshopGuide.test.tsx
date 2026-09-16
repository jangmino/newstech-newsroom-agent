import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, QueryConditions } from "./types";
import { workshopQuestion } from "./workshopScenarios";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function ambiguousPlan() {
  const plan = examplePlan();
  plan.question = workshopQuestion;
  Object.assign(plan.query_plan, {
    entity: null, metric: null, period: null, comparison: null, filters: { frequency: "연간" },
    clarification_required: true, clarification_questions: ["기간과 비교 기준을 확인해 주세요."],
  });
  plan.required_fields = ["entity", "metric", "period", "comparison", "filters.age_range"];
  return plan;
}

function guidedResult(conditions: QueryConditions) {
  const result = exampleResult(ambiguousPlan(), conditions);
  result.query_plan.clarification_required = false;
  result.query_plan.clarification_questions = [];
  const calculation = result.calculation!;
  [calculation.start_year, calculation.end_year] = conditions.period.split("-").map(Number);
  if (conditions.metric === "취업자 수") {
    calculation.input_unit = "천 명";
    calculation.result_unit = "%";
    result.evidence.unit = "입력 천 명 · 결과 %";
    result.evidence.formula = "(종료 값 - 시작 값) / 시작 값 × 100";
    calculation.rows = [
      { region: "가상 지역 A", start_value: "10", end_value: "14", change: "40.00", rank: 1, status: "calculated", reason: null },
    ];
  }
  if (conditions.metric === "취업자 수" && conditions.period === "2020-2024") {
    calculation.rows = [
      { region: "가상 지역 B", start_value: "50", end_value: "70", change: "40.00", rank: 1, status: "calculated", reason: null },
      { region: "가상 지역 A", start_value: "0", end_value: "16", change: null, rank: null, status: "zero_baseline", reason: "시작 값이 0이므로 증감률을 계산할 수 없습니다." },
      { region: "가상 지역 C", start_value: "80", end_value: null, change: null, rank: null, status: "missing_value", reason: "종료 값이 없어 계산에서 제외했습니다." },
    ];
    calculation.warnings = ["계산 가능한 일부 지역만 순위를 매겼습니다."];
  }
  return result;
}

function mockGuideApi() {
  return vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") return json(ambiguousPlan());
    if (path !== "/api/v1/execute") throw new Error("Unexpected endpoint");
    const body = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(Object.keys(body).sort()).toEqual(["approved", "conditions", "mode", "question"]);
    expect(body.approved).toBe(true);
    expect(body.mode).toBe("mock");
    return json(guidedResult(body.conditions));
  });
}

function guide() {
  return within(screen.getByRole("region", { name: "막히는 상황 체험" }));
}

async function analyze() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("heading", { name: "KOSIS" });
}

async function approve() {
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  return await screen.findByRole("region", { name: "이 결과의 실습 검토" });
}

function apply(label: string) {
  fireEvent.click(guide().getByRole("button", { name: label }));
}

test("starting a lesson selects the existing question without analyzing or approving it", () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value).toBe(workshopQuestion);
  expect(guide().getByRole<HTMLButtonElement>("button", { name: "예시 조건 넣기" }).disabled).toBe(true);
  expect(guide().getByRole("status").textContent).toContain("질문 분석");
  expect(screen.queryByRole("table")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

test("ambiguous conditions stay empty until explicitly filled, and a separate approval is required", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  await analyze();
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  apply("예시 조건 넣기");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "청년 연령 범위" }).value).toBe("15-29세");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(guide().getByRole("status").textContent).toContain("실습 검토");
});

test("unsupported period blocks execution and fixing it still requires approval", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("2. 지원 범위 밖 기간");
  await analyze();
  apply("지원하지 않는 기간 넣기");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2019-2024");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  expect(screen.getByText(/가상 청년 고용 자료는 2020~2024년만 지원/)).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  apply("기간을 2020-2024로 수정");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(false);
  expect(fetch).toHaveBeenCalledTimes(1);
  await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("missing-value recovery changes only the period, hides old results and resets review on reapproval", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("3. 0 기준값과 누락값");
  await analyze();
  apply("계산 불가 예시 조건 넣기");
  expect(guide().queryByRole("button", { name: "기간을 2021-2023으로 수정" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  const review = await approve();
  expect(guide().getByRole("status").textContent).toContain("계산 불가 결과가 있습니다");
  const table = screen.getByRole("table", { name: "2020~2024년 시작·종료 값 비교" });
  expect(within(table).getByText("0")).toBeTruthy();
  expect(within(table).getByText("값 없음")).toBeTruthy();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  apply("기간을 2021-2023으로 수정");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "청년 연령 범위" }).value).toBe("15-34세");
  const newReview = await approve();
  expect(within(newReview).getByRole("status").textContent).toContain("0/4");
  expect(screen.getByRole("region", { name: "조건 변경 전후 비교" })).toBeTruthy();
  const requests = fetch.mock.calls.filter(([path]) => path === "/api/v1/execute")
    .map(([, init]) => (JSON.parse(String(init?.body)) as ExecuteRequest).conditions);
  expect(requests[1]).toEqual({ ...requests[0], period: "2021-2023" });
  expect(guide().getByRole("status").textContent).toContain("이번 결과에는 계산 불가 값이 없습니다");
  expect(guide().getByText(/비교 범위가 달라지므로/)).toBeTruthy();
});

test("a plan failure keeps the lesson and question, and can be retried", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  fetch.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("alert");
  expect(guide().getByRole("status").textContent).toContain("질문 분석을 완료하지 못했습니다");
  expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value).toBe(workshopQuestion);
  await analyze();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(guide().getByRole<HTMLButtonElement>("button", { name: "예시 조건 넣기" }).disabled).toBe(false);
});

test("an execution failure shows retry guidance without claiming recovery or changing inputs", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("3. 0 기준값과 누락값");
  await analyze();
  apply("계산 불가 예시 조건 넣기");
  fetch.mockResolvedValueOnce(json({ detail: { code: "invalid_mock_data", message: "계산을 중단했습니다.", field_errors: {} } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByRole("alert");
  expect(guide().getByRole("status").textContent).toContain("요청이 완료되지 않았습니다");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(screen.queryByRole("table")).toBeNull();
  expect(guide().queryByRole("button", { name: "기간을 2021-2023으로 수정" })).toBeNull();
  await approve();
  expect(guide().getByRole("status").textContent).toContain("계산 불가 결과가 있습니다");
});

test("starting another scene clears results and comparison baseline instead of silently reusing them", async () => {
  mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  await analyze();
  apply("예시 조건 넣기");
  await approve();
  apply("3. 0 기준값과 누락값");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  await analyze();
  apply("계산 불가 예시 조건 넣기");
  await approve();
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
});

test("switching scenes while a query is pending rejects the late response", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  await analyze();
  apply("예시 조건 넣기");
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect(guide().getByRole<HTMLButtonElement>("button", { name: "예시 조건 넣기" }).disabled).toBe(true);
  const request = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  apply("2. 지원 범위 밖 기간");
  await act(async () => { finish(json(guidedResult(request.conditions))); });
  expect(screen.queryByRole("table")).toBeNull();
  expect(guide().getByRole("status").textContent).toContain("질문 분석");
});

test("manual condition edits remain editable, while question edits end the guide", async () => {
  mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  await analyze();
  apply("예시 조건 넣기");
  fireEvent.change(screen.getByRole("combobox", { name: "지표" }), { target: { value: "취업자 수" } });
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "지표" }).value).toBe("취업자 수");
  expect(guide().getByRole("status").textContent).toContain("입력한 조건을 확인");
  fireEvent.change(screen.getByRole("textbox", { name: "질문 입력" }), { target: { value: "다른 질문" } });
  expect(guide().queryByRole("status")).toBeNull();
  expect(guide().getAllByRole("button").every((button) => button.getAttribute("aria-pressed") === "false")).toBe(true);
});

test("closing only the guide preserves the approved result and checks without extra requests", async () => {
  const fetch = mockGuideApi();
  render(<App />);
  apply("1. 모호한 질문");
  await analyze();
  apply("예시 조건 넣기");
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  apply("안내 닫기");
  expect(guide().queryByRole("status")).toBeNull();
  expect(within(review).getByRole("status").textContent).toContain("1/4");
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("reanalyzing keeps the guide but clears prepared conditions and results", async () => {
  mockGuideApi();
  render(<App />);
  apply("2. 지원 범위 밖 기간");
  await analyze();
  apply("지원하지 않는 기간 넣기");
  await analyze();
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("");
  expect(guide().getByRole("button", { name: "2. 지원 범위 밖 기간" }).getAttribute("aria-pressed")).toBe("true");
  expect(guide().queryByRole("button", { name: "기간을 2020-2024로 수정" })).toBeNull();
});
