import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
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
