import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./LegacyApp";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, PlanRequest } from "./types";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function geminiPlan() {
  return { ...examplePlan(), interpretation_method: "gemini" as const, interpretation_model: "gemini-3.8-flash" };
}

function mockApi() {
  return vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") {
      const body = JSON.parse(String(init?.body)) as PlanRequest;
      expect(body.mode).toBe("mock");
      return json(body.interpretation_method === "gemini" ? geminiPlan() : examplePlan());
    }
    expect(path).toBe("/api/v1/execute");
    const body = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(Object.keys(body).sort()).toEqual(["approved", "conditions", "mode", "question"]);
    expect(body.mode).toBe("mock");
    expect(body.approved).toBe(true);
    return json(exampleResult(geminiPlan(), body.conditions));
  });
}

function selectMethod(value: "gemini" | "mock_rules") {
  fireEvent.change(screen.getByRole("combobox", { name: "질문 해석 방식" }), { target: { value } });
}

async function analyze() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("heading", { name: "KOSIS" });
}

async function approve() {
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  return await screen.findByRole("region", { name: "이 결과의 실습 검토" });
}

test("mock is the default, choosing Gemini explains transmission without sending a request", async () => {
  const fetch = mockApi();
  render(<App />);
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "질문 해석 방식" }).value).toBe("mock_rules");
  expect(screen.getByText(/질문을 외부로 보내지 않고/)).toBeTruthy();
  selectMethod("gemini");
  expect(screen.getByText(/입력한 질문을 Google의 Gemini로 보냅니다/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
  await analyze();
  expect(screen.getByText("질문 해석: Gemini (gemini-3.8-flash) · 자료 조회와 브리핑은 모의 자료입니다.")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("region", { name: "이 결과의 실습 검토" }).textContent).toContain("기사 사용 승인이 아닙니다");
});

test("changing interpretation method invalidates conditions, results, comparison and review", async () => {
  mockApi();
  render(<App />);
  selectMethod("gemini");
  await analyze();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  const question = screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value;
  selectMethod("mock_rules");
  expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "질문 입력" }).value).toBe(question);
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  await analyze();
  expect(screen.getByText("질문 해석: 모의 규칙 · Gemini를 호출하지 않았습니다.")).toBeTruthy();
  const next = await approve();
  expect(within(next).getByRole("status").textContent).toContain("0/4");
  expect(screen.queryByRole("region", { name: "조건 변경 전후 비교" })).toBeNull();
});

test.each(["planner_disabled", "planner_configuration_error", "planner_timeout", "planner_rate_limited", "invalid_planner_output"])("%s stays on Gemini and never silently falls back", async (code) => {
  const fetch = mockApi();
  render(<App />);
  selectMethod("gemini");
  fetch.mockResolvedValueOnce(json({ detail: { code, message: "Gemini 해석을 완료하지 못했습니다. 다시 시도해 주세요.", field_errors: {} } }, code === "planner_rate_limited" ? 429 : 503));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  expect((await screen.findByRole("alert")).textContent).toContain("다시 시도");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "질문 해석 방식" }).value).toBe("gemini");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  await analyze();
  expect(fetch).toHaveBeenCalledTimes(2);
  const request = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as PlanRequest;
  expect(request.interpretation_method).toBe("gemini");
  expect(screen.queryByRole("table")).toBeNull();
});

test("a late Gemini response cannot restore a plan after switching methods", async () => {
  const fetch = mockApi();
  render(<App />);
  selectMethod("gemini");
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  selectMethod("mock_rules");
  await act(async () => { finish(json(geminiPlan())); });
  expect(screen.queryByRole("heading", { name: "KOSIS" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  await analyze();
  expect(screen.getByText("질문 해석: 모의 규칙 · Gemini를 호출하지 않았습니다.")).toBeTruthy();
});
