import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { WorkshopAccess } from "./WorkshopAccess";
import { postJson } from "./api";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest } from "./types";

// Synthetic fixture, never a local or event credential.
const code = "test-only-workshop-credential";
const ready = { required: true, available: true };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

function setup(required = true) {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/access") {
      if (init?.method === "POST") expect(new Headers(init.headers).get("X-Workshop-Code")).toBe(code);
      return json({ required, available: true });
    }
    expect(new Headers(init?.headers).get("X-Workshop-Code")).toBe(required ? code : null);
    if (path === "/api/v1/plan") return json(examplePlan());
    expect(path).toBe("/api/v1/execute");
    const body = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(body.approved).toBe(true);
    return json(exampleResult(examplePlan(), body.conditions));
  });
  return { fetch, view: render(<WorkshopAccess />) };
}

async function submitCode(value = code) {
  const input = await screen.findByLabelText("행사 접근코드");
  fireEvent.change(input, { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "실습 입장" }));
}

async function enter() {
  await submitCode();
  await screen.findByRole("button", { name: "질문 분석" });
}

async function plan() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("button", { name: "이 조건으로 조회" });
}

async function approve() {
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  return screen.findByRole("region", { name: "이 결과의 실습 검토" });
}

test("entry checks access only; accepted code is header-only and approval stays separate", async () => {
  const { fetch } = setup();
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  await screen.findByLabelText("행사 접근코드");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("행사 접근코드").getAttribute("type")).toBe("password");
  await enter();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  await plan();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  const review = await approve();
  expect(within(review).getByRole("status").textContent).toContain("0/4");
  for (const [path, init] of fetch.mock.calls) {
    expect(String(path)).not.toContain(code);
    expect(String(init?.body)).not.toContain(code);
    expect(init?.credentials).toBe("omit");
    expect(init?.cache).toBe("no-store");
    expect(init?.redirect).toBe("error");
  }
  expect(document.body.textContent).not.toContain(code);
  expect(localStorage.setItem).not.toHaveBeenCalled();
  expect(document.cookie).toBe("");
});

test("local access disabled keeps the original mock approval flow with no code header", async () => {
  const { fetch } = setup(false);
  await screen.findByRole("button", { name: "질문 분석" });
  expect(screen.queryByLabelText("행사 접근코드")).toBeNull();
  expect(screen.queryByRole("button", { name: "실습 나가기" })).toBeNull();
  await plan();
  await approve();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each(["short", `${code} `, "한글".repeat(16)])("malformed code stays at entry without a request: %s", async (value) => {
  const { fetch } = setup();
  await submitCode(value);
  expect(screen.getByRole("alert").textContent).toContain("그대로 입력");
  expect(screen.getByLabelText<HTMLInputElement>("행사 접근코드").value).toBe("");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("wrong code uses safe Korean message, clears the field, and permits explicit retry", async () => {
  const { fetch } = setup();
  await screen.findByLabelText("행사 접근코드");
  fetch.mockResolvedValueOnce(json({ detail: { message: code } }, 401));
  await submitCode();
  expect((await screen.findByRole("alert")).textContent).toContain("일치하지 않습니다");
  expect(document.body.textContent).not.toContain(code);
  expect(screen.getByLabelText<HTMLInputElement>("행사 접근코드").value).toBe("");
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  await enter();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each(["network", "malformed", "unavailable"])("status %s fails closed and allows status retry", async (failure) => {
  const { fetch } = setup();
  // An unsuccessful status refresh must never fall back to an open workshop.
  await screen.findByLabelText("행사 접근코드");
  if (failure === "network") fetch.mockRejectedValueOnce(new Error(code));
  else fetch.mockResolvedValueOnce(json(failure === "malformed" ? { required: "false" } : { required: true, available: false }));
  fireEvent.click(screen.getByRole("button", { name: "입장 상태 다시 확인" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  expect(screen.queryByLabelText("행사 접근코드")).toBeNull();
  expect(document.body.textContent).not.toContain(code);
  fireEvent.click(screen.getByRole("button", { name: "입장 상태 다시 확인" }));
  await screen.findByLabelText("행사 접근코드");
});

test.each(["network", "malformed", "unavailable"])("entry %s never opens the workshop", async (failure) => {
  const { fetch } = setup();
  await screen.findByLabelText("행사 접근코드");
  if (failure === "network") fetch.mockRejectedValueOnce(new Error(code));
  else fetch.mockResolvedValueOnce(json({}, failure === "unavailable" ? 503 : 200));
  await submitCode();
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  expect(document.body.textContent).not.toContain(code);
});

test("leaving removes results, comparison, review and code; reentry does not repeat requests", async () => {
  const { fetch } = setup();
  await enter();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  await approve();
  expect(screen.getByRole("article", { name: "이전 승인 결과" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "실습 나가기" }));
  expect(screen.queryByRole("article", { name: "이전 승인 결과" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.getByLabelText<HTMLInputElement>("행사 접근코드").value).toBe("");
  const count = fetch.mock.calls.length;
  await enter();
  expect(fetch).toHaveBeenCalledTimes(count + 1);
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  await plan();
  expect(within(await approve()).getByRole("status").textContent).toContain("0/4");
});

test.each(["plan", "execute", "unavailable"])("access rejection on %s removes the workshop and never auto-retries", async (stage) => {
  const { fetch } = setup();
  await enter();
  await plan();
  await approve();
  fetch.mockResolvedValueOnce(json({ detail: { code: stage === "unavailable"
    ? "workshop_access_unavailable" : "workshop_access_required", message: code, field_errors: {} } },
  stage === "unavailable" ? 503 : 401));
  fireEvent.click(screen.getByRole("button", { name: stage === "plan" ? "질문 분석" : "이 조건으로 조회" }));
  await screen.findByRole("heading", { name: "행사 접근코드 확인" });
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByRole("button", { name: "저장 자료로 조건 다시 확인" })).toBeNull();
  expect(document.body.textContent).not.toContain(code);
  const count = fetch.mock.calls.length;
  if (stage === "unavailable") {
    expect(screen.queryByLabelText("행사 접근코드")).toBeNull();
  } else {
    await enter();
    expect(fetch).toHaveBeenCalledTimes(count + 1);
    expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  }
});

test.each(["entry", "plan", "execute"])("late %s response after cancel/leave cannot reopen or replace a session", async (stage) => {
  const { fetch } = setup();
  await screen.findByLabelText("행사 접근코드");
  if (stage !== "entry") await enter();
  if (stage === "execute") await plan();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  if (stage === "entry") await submitCode();
  else fireEvent.click(screen.getByRole("button", { name: stage === "plan" ? "질문 분석" : "이 조건으로 조회" }));
  const signal = fetch.mock.lastCall?.[1]?.signal;
  fireEvent.click(screen.getByRole("button", { name: stage === "entry" ? "입장 취소" : "실습 나가기" }));
  expect(signal?.aborted).toBe(true);
  await enter();
  await act(async () => finish(stage === "entry" ? json(ready) : json({}, 401)));
  expect(screen.getByRole("button", { name: "질문 분석" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("refresh/remount forgets the code and requires entry again", async () => {
  const { view, fetch } = setup();
  await enter();
  view.unmount();
  render(<WorkshopAccess />);
  await screen.findByLabelText("행사 접근코드");
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  expect(new Headers(fetch.mock.lastCall?.[1]?.headers).get("X-Workshop-Code")).toBeNull();
});

test("credential-bearing helper refuses external or unrelated URLs", async () => {
  for (const path of ["https://example.com/api/v1/plan", "//example.com/api/v1/execute", "/api/v1/plan?code=x", "/health"]) {
    await expect(postJson(path, { question: "청년 고용률", mode: "mock" }, new AbortController().signal, code))
      .rejects.toThrow("지원하지 않는 요청");
  }
  expect(fetch).not.toHaveBeenCalled();
});

test("protection enabled after an open local start locks the next rejected request", async () => {
  const { fetch } = setup(false);
  await screen.findByRole("button", { name: "질문 분석" });
  fetch.mockResolvedValueOnce(json({}, 401));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByLabelText("행사 접근코드");
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
});

test("ordinary provider failure keeps admission and requires manual retry", async () => {
  const { fetch } = setup();
  await enter();
  await plan();
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "invalid_mock_data", message: "자료를 확인하지 못했습니다.", field_errors: {},
  } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toBe("자료를 확인하지 못했습니다.");
  expect(screen.getByRole("button", { name: "실습 나가기" })).toBeTruthy();
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(fetch).toHaveBeenCalledTimes(4);
  await approve();
});
