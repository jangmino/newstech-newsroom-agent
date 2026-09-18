import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./LegacyApp";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, ExecutionResponse } from "./types";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockApi(source: "kosis" | "opendart" = "kosis") {
  const plan = examplePlan(source);
  let latest: ExecutionResponse | undefined;
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") return json(plan);
    if (path !== "/api/v1/execute") throw new Error(`Unexpected test endpoint: ${path}`);
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(request.approved).toBe(true);
    expect(request.mode).toBe("mock");
    latest = exampleResult(plan, request.conditions);
    return json(latest);
  });
  return { fetch, latest: () => latest };
}

async function planQuestion() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("button", { name: "이 조건으로 조회" });
}

async function approve() {
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  return await screen.findByRole("region", { name: "이 결과의 실습 검토" });
}

async function approvedResult(source: "kosis" | "opendart" = "kosis") {
  const api = mockApi(source);
  const view = render(<App />);
  if (source === "opendart") fireEvent.click(screen.getByRole("button", { name: "삼성전자의 최근 실적은 악화됐는가?" }));
  await planQuestion();
  const panel = await approve();
  return { ...api, ...view, panel };
}

function checkAll(panel: HTMLElement) {
  for (const checkbox of within(panel).getAllByRole("checkbox")) fireEvent.click(checkbox);
}

function expectEmptyReview(panel: HTMLElement) {
  expect(within(panel).getByRole("status").textContent).toBe("실습 검토 전 · 0/4개 확인");
  expect(within(panel).getAllByRole<HTMLInputElement>("checkbox").every((item) => !item.checked)).toBe(true);
}

test("mock interpretation is labeled and unresolved output requires a choice before approval", async () => {
  const { fetch } = mockApi();
  const plan = examplePlan();
  plan.query_plan.period = "";
  plan.query_plan.clarification_required = true;
  plan.query_plan.clarification_questions = ["가상 청년 고용 자료는 2020~2024년만 지원합니다. 기간을 수정해 주세요."];
  plan.required_fields = ["period"];
  fetch.mockResolvedValueOnce(json(plan));
  render(<App />);
  await planQuestion();
  expect(screen.getByText("질문 해석: 모의 규칙 · Gemini를 호출하지 않았습니다.")).toBeTruthy();
  const notes = screen.getByText("처음 질문을 해석할 때 확인이 필요했던 내용").closest("details")!;
  fireEvent.click(within(notes).getByText("처음 질문을 해석할 때 확인이 필요했던 내용"));
  expect(notes.textContent).toContain("기간을 수정해 주세요");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2021-2023" } });
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(false);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(notes.textContent).toContain("현재 조회 가능 여부는 입력란 아래의 안내");
  await approve();
  const request = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  expect(request.conditions.period).toBe("2021-2023");
  expect(request.approved).toBe(true);
});

test("an unresolved source asks for a question edit without offering condition approval", async () => {
  const { fetch } = mockApi();
  const plan = examplePlan();
  plan.query_plan.selected_source = "undetermined";
  plan.query_plan.selection_reason = "두 자료원이 함께 언급됐다면 질문을 나누어 주세요.";
  plan.query_plan.clarification_required = true;
  plan.query_plan.clarification_questions = ["자료원을 정할 수 있도록 질문을 구체화해 주세요."];
  plan.field_options = {};
  plan.available_years = [];
  plan.required_fields = ["selected_source"];
  fetch.mockResolvedValueOnce(json(plan));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("heading", { name: "자료원 확인 필요" });
  expect(screen.getByText(/질문을 나누어 주세요/)).toBeTruthy();
  expect(screen.queryByText("처음 질문을 해석할 때 확인이 필요했던 내용")).toBeNull();
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each(["invalid_planner_output", "planner_unavailable"])("%s clears old results, retains the question and permits a new plan", async (code) => {
  const { fetch, panel } = await approvedResult();
  checkAll(panel);
  const message = "질문을 해석하지 못했습니다. ‘질문 분석’을 다시 눌러 주세요.";
  fetch.mockResolvedValueOnce(json({ detail: { code, message, field_errors: {} } }, 503));
  const question = screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value;
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  expect((await screen.findByRole("alert")).textContent).toBe(message);
  expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value).toBe(question);
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  await planQuestion();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expectEmptyReview(await approve());
});

test("review is absent before approval and during loading, then starts unchecked", async () => {
  const { fetch } = mockApi();
  render(<App />);
  expect(screen.queryByRole("checkbox")).toBeNull();
  await planQuestion();
  expect(screen.queryByRole("checkbox")).toBeNull();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect(screen.queryByRole("checkbox")).toBeNull();
  const body = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  await act(async () => { finish(json(exampleResult(examplePlan(), body.conditions))); });
  expectEmptyReview(await screen.findByRole("region", { name: "이 결과의 실습 검토" }));
});

test("checks update progress and briefing badge, can be undone, and never approve journalism", async () => {
  const { panel, fetch, latest } = await approvedResult();
  expectEmptyReview(panel);
  const boxes = within(panel).getAllByRole<HTMLInputElement>("checkbox");
  fireEvent.click(boxes[0]);
  expect(within(panel).getByRole("status").textContent).toBe("실습 검토 중 · 1/4개 확인");
  for (const box of boxes.slice(1)) fireEvent.click(box);
  const complete = "실습 검토 항목 확인 완료 · 4/4개 확인";
  expect(within(panel).getByRole("status").textContent).toBe(complete);
  expect(within(screen.getByRole("article", { name: "근거 기반 브리핑" })).getByRole("link", { name: complete }).getAttribute("href")).toBe("#review-title");
  expect(panel.textContent).toContain("사실 검증 완료나 기사 사용 승인이 아닙니다.");
  expect(latest()?.brief.verification_status).toBe("review_required");
  expect(fetch).toHaveBeenCalledTimes(2);
  fireEvent.click(boxes[0]);
  expect(within(panel).getByRole("status").textContent).toBe("실습 검토 중 · 3/4개 확인");
  for (const box of boxes.slice(1)) fireEvent.click(box);
  expectEmptyReview(panel);
  expect(screen.getByRole("heading", { name: "가상 원자료와 계산 결과" })).toBeTruthy();
});

test.each([
  ["대상", "수도권 시·도"], ["지표", "취업자 수"], ["기간", "2021-2024"],
  ["비교 기준", "증감률"], ["청년 연령 범위", "15-34세"],
])("changing %s discards review and requires fresh checks after reapproval", async (label, value) => {
  const { panel } = await approvedResult();
  checkAll(panel);
  fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expectEmptyReview(await approve());
});

test.each(["edit", "sample", "reanalyze"])("question action %s resets the review", async (action) => {
  const { panel } = await approvedResult();
  checkAll(panel);
  if (action === "edit") fireEvent.change(screen.getByLabelText("질문 입력"), { target: { value: "청년 고용 조건을 다시 비교" } });
  if (action === "sample") fireEvent.click(screen.getByRole("button", { name: "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?" }));
  if (action !== "reanalyze") expect(screen.queryByRole("checkbox")).toBeNull();
  await planQuestion();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expectEmptyReview(await approve());
});

test("re-querying identical conditions resets progress even if result ID is reused", async () => {
  const { panel } = await approvedResult();
  checkAll(panel);
  expectEmptyReview(await approve());
});

test("failed re-query discards old review and a retry starts fresh", async () => {
  const { panel, fetch } = await approvedResult();
  checkAll(panel);
  fetch.mockResolvedValueOnce(json({ detail: { code: "invalid_mock_data", message: "가상 자료 계산을 중단했습니다.", field_errors: {} } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("계산을 중단");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expectEmptyReview(await approve());
});

test("a late response cannot restore a review after conditions change", async () => {
  const { panel, fetch, latest } = await approvedResult();
  checkAll(panel);
  const stale = latest();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  fireEvent.change(screen.getByLabelText("기간", { exact: true }), { target: { value: "2021-2024" } });
  await act(async () => { finish(json(stale)); });
  expect(screen.queryByRole("checkbox")).toBeNull();
  expectEmptyReview(await approve());
});

test("OpenDART review acknowledges absent numbers and cannot imply calculation", async () => {
  const { panel } = await approvedResult("opendart");
  expect(panel.textContent).toContain("원자료 숫자와 계산 결과가 없으며");
  expect(panel.textContent).not.toContain("가상 입력값");
  checkAll(panel);
  expect(within(panel).getByRole("status").textContent).toContain("4/4개 확인");
  expect(screen.queryByRole("heading", { name: "가상 원자료와 계산 결과" })).toBeNull();
});

test("completing a review does not dismiss missing-data warnings or create a rank", async () => {
  const { fetch } = mockApi();
  render(<App />);
  await planQuestion();
  fetch.mockImplementationOnce(async (_path, init) => {
    const body = JSON.parse(String(init?.body)) as ExecuteRequest;
    const result = exampleResult(examplePlan(), body.conditions);
    result.calculation!.rows = [{ region: "가상 지역 A", start_value: "40", end_value: null,
      change: null, rank: null, status: "missing_value", reason: "종료 값이 없습니다." }];
    result.calculation!.warnings = ["계산 가능한 가상 지역이 0개여서 순위를 매기지 않았습니다."];
    return json(result);
  });
  const panel = await approve();
  checkAll(panel);
  const table = screen.getByRole("table", { name: "2020~2024년 시작·종료 값 비교" });
  expect(within(table).getByText("계산 불가")).toBeTruthy();
  expect(within(table).getByText("순위 없음")).toBeTruthy();
  expect(screen.getByText("계산 가능한 가상 지역이 0개여서 순위를 매기지 않았습니다.")).toBeTruthy();
  expect(within(panel).getByRole("status").textContent).toContain("4/4개 확인");
});

test("remounting the app loses review state instead of restoring it from storage", async () => {
  const { panel, unmount } = await approvedResult();
  checkAll(panel);
  unmount();
  render(<App />);
  expect(screen.queryByRole("checkbox")).toBeNull();
  await planQuestion();
  expectEmptyReview(await approve());
});

function comparisonRow(label: string) {
  const table = screen.getByRole("table", { name: "승인 조건 비교" });
  const header = within(table).getByRole("rowheader", { name: new RegExp(`^${label}`) });
  return header.closest("tr")!;
}

function changePeriod(value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value } });
}

test("only two successful approvals with changed conditions show a comparison and fresh review", async () => {
  const { panel, fetch } = await approvedResult();
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  checkAll(panel);
  changePeriod("2021-2024");
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  expect(screen.queryByRole("article", { name: "이전 승인 결과" })).toBeNull();
  const newReview = await approve();
  expectEmptyReview(newReview);
  expect(screen.getByRole("region", { name: "조건 변경 전후 비교" })).toBeTruthy();
  expect(within(comparisonRow("기간")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["2020-2024", "2021-2024"]);
  expect(within(comparisonRow("기간")).getByText("변경")).toBeTruthy();
  expect(within(comparisonRow("지표")).queryByText("변경")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each([
  ["대상", "수도권 시·도"], ["지표", "취업자 수"], ["비교 기준", "증감률"],
  ["청년 연령 범위", "15-34세"],
])("the comparison includes changes to %s", async (label, value) => {
  await approvedResult();
  fireEvent.change(screen.getByRole("combobox", { name: label }), { target: { value } });
  await approve();
  expect(within(comparisonRow(label)).getByText("변경")).toBeTruthy();
  expect(within(comparisonRow(label)).getAllByRole("cell")[1].textContent).toBe(value);
});

test("a third successful query compares the immediately previous success, not the first result", async () => {
  await approvedResult();
  changePeriod("2021-2024");
  await approve();
  changePeriod("2022-2024");
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  await approve();
  expect(within(comparisonRow("기간")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["2021-2024", "2022-2024"]);
});

test("same conditions and edit-then-revert do not fabricate a condition difference", async () => {
  await approvedResult();
  changePeriod("2021-2024");
  changePeriod("2020-2024");
  await approve();
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  changePeriod("2021-2024");
  await approve();
  expect(screen.getByRole("region", { name: "조건 변경 전후 비교" })).toBeTruthy();
  await approve();
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
});

test("failure keeps the last successful comparison baseline hidden until retry succeeds", async () => {
  const { fetch } = await approvedResult();
  changePeriod("2021-2024");
  fetch.mockResolvedValueOnce(json({ detail: { code: "invalid_mock_data", message: "계산을 중단했습니다.", field_errors: {} } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  expect(screen.queryByRole("article", { name: "이전 승인 결과" })).toBeNull();
  changePeriod("2022-2024");
  expectEmptyReview(await approve());
  expect(within(comparisonRow("기간")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["2020-2024", "2022-2024"]);
});

test("a late response cannot replace the comparison baseline or current comparison", async () => {
  const { fetch } = await approvedResult();
  changePeriod("2021-2024");
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
  const staleRequest = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  changePeriod("2022-2024");
  await approve();
  await act(async () => { finish(json(exampleResult(examplePlan(), staleRequest.conditions))); });
  expect(within(comparisonRow("기간")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["2020-2024", "2022-2024"]);
  changePeriod("2023-2024");
  await approve();
  expect(within(comparisonRow("기간")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["2022-2024", "2023-2024"]);
});

test.each(["edit", "sample", "reanalyze", "remount"])("%s clears the comparison baseline even when the next query has different conditions", async (action) => {
  const { unmount } = await approvedResult();
  changePeriod("2021-2024");
  await approve();
  if (action === "edit") {
    fireEvent.change(screen.getByLabelText("질문 입력"), { target: { value: "새로운 청년 고용 질문" } });
  } else if (action === "sample") {
    fireEvent.click(screen.getByRole("button", { name: "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?" }));
  } else if (action === "remount") {
    unmount();
    render(<App />);
  }
  await planQuestion();
  changePeriod("2022-2024");
  await approve();
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
});

test("OpenDART compares changed statement basis without claiming numeric results", async () => {
  await approvedResult("opendart");
  fireEvent.change(screen.getByRole("combobox", { name: "재무제표 기준" }), { target: { value: "별도" } });
  await approve();
  expect(within(comparisonRow("재무제표 기준")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["연결", "별도"]);
  const comparison = screen.getByRole("region", { name: "조건 변경 전후 비교" });
  expect(comparison.textContent).toContain("원자료 숫자와 계산 결과가 없어 수치 변화는 비교하지 않습니다.");
  expect(within(comparison).queryByRole("table", { name: /가상 지역별/ })).toBeNull();
});
