import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
// Access regression harness remains on the original UI contract.
vi.mock("./App", () => import("./LegacyApp"));
import App from "./LegacyApp";
import { WorkshopAccess } from "./WorkshopAccess";
import { withRequestReference } from "./api";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest } from "./types";

const id = "ee4594d9-07e1-4c71-8893-0976e2a79d39";
const otherId = "f076f55a-9722-4ed3-b33c-b224d21cc807";
const testCode = "test-only-workshop-credential";
function json(body: unknown, status = 200, identifier = id) {
  return new Response(JSON.stringify(body), { status, headers: { "X-Request-ID": identifier } });
}
function failure(status = 503, code = "planner_unavailable", identifier = id) {
  return json({ detail: { code, message: "요청을 확인하지 못했습니다.", field_errors: {} } }, status, identifier);
}
function setup() {
  return vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/access") return json({ required: true, available: true });
    if (path === "/api/v1/plan") return json(examplePlan());
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    return json(exampleResult(examplePlan(), request.conditions));
  });
}
async function plan() {
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  await screen.findByRole("button", { name: "이 조건으로 조회" });
}
async function enter() {
  fireEvent.change(await screen.findByLabelText("행사 접근코드"), { target: { value: testCode } });
  fireEvent.click(screen.getByRole("button", { name: "실습 입장" }));
  await screen.findByRole("button", { name: "질문 분석" });
}

test.each(["plan", "execute"])("%s failure shows reference without results; editing clears it", async (stage) => {
  const fetch = setup();
  render(<App />);
  if (stage === "execute") await plan();
  fetch.mockResolvedValueOnce(failure());
  fireEvent.click(screen.getByRole("button", { name: stage === "plan" ? "질문 분석" : "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain(`문의용 요청 번호: ${id}`);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "질문 입력" }), { target: { value: "다른 고용 질문" } });
  expect(screen.queryByText(new RegExp(id))).toBeNull();
});

test("retry replaces the old reference, and successful approval removes it", async () => {
  const fetch = setup();
  render(<App />);
  await plan();
  fetch.mockResolvedValueOnce(failure());
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByText(new RegExp(id));
  fetch.mockResolvedValueOnce(failure(503, "planner_unavailable", otherId));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByText(new RegExp(otherId));
  expect(screen.queryByText(new RegExp(id))).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByRole("region", { name: "이 결과의 실습 검토" });
  expect(screen.queryByText(/문의용 요청 번호/)).toBeNull();
});

test.each(["", "private-code-marker", `${id},${otherId}`, `<script>${id}</script>`, "x".repeat(1000)])("malformed reference is never echoed: %s", (identifier) => {
  const text = withRequestReference("안내", json({}, 503, identifier));
  expect(text).toBe("안내");
});

test("network failure has no invented reference", async () => {
  const fetch = setup();
  render(<App />);
  fetch.mockRejectedValueOnce(new Error(`private-transport-error ${id}`));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  expect((await screen.findByRole("alert")).textContent).toContain("연결 상태");
  expect(screen.queryByText(/문의용 요청 번호|private-transport-error/)).toBeNull();
});

test("invalid response JSON uses the response header reference", async () => {
  const fetch = setup();
  render(<App />);
  fetch.mockResolvedValueOnce(new Response("not-json", { headers: { "X-Request-ID": id } }));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  expect((await screen.findByRole("alert")).textContent).toContain(id);
});

test.each(["status", "entry", "protected"])("%s access failure preserves only a safe support reference", async (stage) => {
  const fetch = setup();
  if (stage === "status") fetch.mockResolvedValueOnce(json({ required: true, available: false }));
  render(<WorkshopAccess />);
  if (stage === "entry") {
    fireEvent.change(await screen.findByLabelText("행사 접근코드"), { target: { value: testCode } });
    fetch.mockResolvedValueOnce(failure(401, "workshop_access_required"));
    fireEvent.click(screen.getByRole("button", { name: "실습 입장" }));
  } else if (stage === "protected") {
    await enter();
    fetch.mockResolvedValueOnce(failure(401, "workshop_access_required"));
    fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  }
  expect((await screen.findByRole("alert")).textContent).toContain(`문의용 요청 번호: ${id}`);
  expect(screen.queryByRole("button", { name: "질문 분석" })).toBeNull();
  expect(document.body.textContent).not.toContain(testCode);
  fireEvent.click(screen.getByRole("button", { name: "입장 상태 다시 확인" }));
  await screen.findByLabelText("행사 접근코드");
  expect(screen.queryByText(/문의용 요청 번호/)).toBeNull();
});

test("late error after leaving cannot show its reference in the entry screen", async () => {
  const fetch = setup();
  render(<WorkshopAccess />);
  await enter();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  fireEvent.click(screen.getByRole("button", { name: "실습 나가기" }));
  await act(async () => finish(failure()));
  expect(screen.queryByText(new RegExp(id))).toBeNull();
  expect(screen.getByLabelText("행사 접근코드")).toBeTruthy();
});
