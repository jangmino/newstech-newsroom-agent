import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import { getJson } from "./api";
import { exampleOperations } from "./test/operationsResponse";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, OperationsStatus } from "./types";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

function setup() {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/operations") return json(exampleOperations());
    if (path === "/api/v1/plan") return json(examplePlan());
    expect(path).toBe("/api/v1/execute");
    return json(exampleResult(examplePlan(), (JSON.parse(String(init?.body)) as ExecuteRequest).conditions));
  });
  return { fetch, view: render(<App />) };
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "실습 운영 상태 보기" }));
  await screen.findByText("설정상 허용 · 실제 연결 미확인");
  return screen.getByRole("region", { name: "실습 운영 상태" });
}

test("explicit open reads status only, labels scope and never reveals evidence before approval", async () => {
  const { fetch } = setup();
  expect(fetch).not.toHaveBeenCalled();
  const panel = await open();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.lastCall?.[0]).toBe("/api/v1/operations");
  expect(fetch.mock.lastCall?.[1]?.method).toBe("GET");
  expect(fetch.mock.lastCall?.[1]?.body).toBeUndefined();
  for (const text of ["사용 꺼짐", "필수 설정 부족 · 운영자 확인 필요", "사용 가능 · 파일 확인됨",
    "사용 불가 · 파일 확인 필요", "3600초", "64건", "최근 60초 30회 · 동시 8회", "최근 60초 30회 · 동시 2회"]) {
    expect(within(panel).getByText(text)).toBeTruthy();
  }
  expect(panel.textContent).toContain("이 서버 프로세스 안에서만");
  expect(panel.textContent).toContain("기사 사용 승인이 아닙니다");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(within(panel).queryByRole("combobox")).toBeNull();
  expect(within(panel).queryByRole("checkbox")).toBeNull();
  expect(localStorage.setItem).not.toHaveBeenCalled();
});

test("refresh and close preserve edited conditions, approved results and human review", async () => {
  const { fetch } = setup();
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("button", { name: "이 조건으로 조회" });
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  const review = await screen.findByRole("region", { name: "이 결과의 실습 검토" });
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  await open();
  fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));
  await screen.findByText("설정상 허용 · 실제 연결 미확인");
  expect(within(review).getByRole("status").textContent).toContain("1/4");
  fireEvent.click(screen.getByRole("button", { name: "운영 상태 닫기" }));
  expect(screen.queryByRole("region", { name: "실습 운영 상태" })).toBeNull();
  expect(screen.getByRole("article", { name: "근거 기반 브리핑" })).toBeTruthy();
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "비교 기준" }).value).toBe("증감률");
  expect(within(review).getByRole("status").textContent).toContain("1/4");
  expect(fetch).toHaveBeenCalledTimes(4);
});

test("loading and refresh failure clear stale status, retain the question and require explicit retry", async () => {
  const { fetch } = setup();
  await open();
  let finish!: (value: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));
  expect(within(screen.getByRole("region", { name: "실습 운영 상태" })).getByRole("status").textContent).toContain("운영 상태를 확인");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "상태 다시 확인" }).disabled).toBe(true);
  expect(screen.queryByText("설정상 허용 · 실제 연결 미확인")).toBeNull();
  const id = "a443d946-ce88-4cd4-9c2d-36975e7e2622";
  await act(async () => finish(new Response("{}", { status: 500, headers: { "X-Request-ID": id } })));
  expect(screen.getByRole("alert").textContent).toContain(id);
  expect(screen.getByRole("button", { name: "질문 분석" })).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));
  await screen.findByText("설정상 허용 · 실제 연결 미확인");
  expect(screen.queryByRole("alert")).toBeNull();
});

test.each(["close", "unmount"])("%s aborts status requests and ignores late responses", async (action) => {
  const { fetch, view } = setup();
  let finish!: (value: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "실습 운영 상태 보기" }));
  const signal = fetch.mock.lastCall?.[1]?.signal;
  if (action === "close") {
    fireEvent.click(screen.getByRole("button", { name: "운영 상태 닫기" }));
    await open();
  } else view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(json({}, 500)));
  expect(screen.queryByRole("alert")).toBeNull();
});

test("network failure gives safe Korean guidance without automatic retries", async () => {
  const { fetch } = setup();
  fetch.mockRejectedValueOnce(new Error("private-connection-details"));
  fireEvent.click(screen.getByRole("button", { name: "실습 운영 상태 보기" }));
  expect((await screen.findByRole("alert")).textContent).toContain("연결 상태");
  expect(document.body.textContent).not.toContain("private-connection-details");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each([
  (data: OperationsStatus) => { data.checked_at = "invalid"; },
  (data: OperationsStatus) => { Object.assign(data, { external_calls_made: true }); },
  (data: OperationsStatus) => { Object.assign(data.providers, { gemini: "connected" }); },
  (data: OperationsStatus) => { data.snapshots.kosis.metadata = null; },
  (data: OperationsStatus) => { Object.assign(data.cache, { scope: "global" }); },
  (data: OperationsStatus) => { data.limits.gemini.requests_per_minute = -1; },
])("malformed status is never presented as operational readiness (%#)", async (mutate) => {
  const { fetch } = setup();
  const data = exampleOperations();
  mutate(data);
  fetch.mockResolvedValueOnce(json(data));
  fireEvent.click(screen.getByRole("button", { name: "실습 운영 상태 보기" }));
  expect((await screen.findByRole("alert")).textContent).toContain("응답을 확인하지 못했습니다");
  expect(screen.queryByText("설정상 허용 · 실제 연결 미확인")).toBeNull();
});

test("disabled snapshot and cache are shown as configuration with no availability claim", async () => {
  const { fetch } = setup();
  const data = exampleOperations();
  data.cache.enabled = false;
  data.snapshots.kosis = { status: "disabled", metadata: null };
  fetch.mockResolvedValueOnce(json(data));
  const panel = await open();
  expect(within(panel).getAllByText("사용 꺼짐")).toHaveLength(3);
  expect(within(panel).queryByText("사용 가능 · 파일 확인됨")).toBeNull();
});

test("GET helper sends the synthetic code only to the fixed same-origin status endpoint", async () => {
  const code = "synthetic-workshop-code";
  const signal = new AbortController().signal;
  vi.mocked(fetch).mockResolvedValue(json(exampleOperations()));
  for (const path of ["https://example.com/api/v1/operations", "//example.com/api/v1/operations", "/api/v1/operations?x=y", "/health"]) {
    await expect(getJson(path, signal, code)).rejects.toThrow("지원하지 않는 요청");
  }
  expect(fetch).not.toHaveBeenCalled();
  await getJson("/api/v1/operations", signal, code);
  expect(fetch).toHaveBeenCalledWith("/api/v1/operations", {
    method: "GET", headers: { "X-Workshop-Code": code }, cache: "no-store",
    credentials: "omit", redirect: "error", signal,
  });
});
