import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./LegacyApp";
import type { ResearchExecuteRequest, ResearchPlan, ResearchResult } from "./researchTypes";

const question = "SK하이닉스 최근 실적이 좋아졌는지 숫자로 확인하고 싶어.";
function plan(): ResearchPlan {
  return {
    request_id: "plan-id", question,
    conditions: { selected_source: "opendart", entity: "SK하이닉스", company_code: "00164779", metrics: ["매출액", "영업이익"], start_year: 2022, end_year: 2024, comparison: "증감 폭", statement_basis: "연결", age_range: "15-29세", frequency: "연간" },
    selection_reason: "기업 공시의 연결 재무제표를 확인합니다.", proposals: ["매출액과 영업이익을 제안합니다."], clarification_questions: [], field_errors: {},
    companies: [{ name: "SK하이닉스", code: "00164779", stock_code: "000660" }], available_years: [2020, 2021, 2022, 2023, 2024], available_entities: [], available_metrics: ["매출액", "영업이익"],
    metadata_notice: "회사·보고서 목록만 확인했습니다.", interpretation_method: "mock_rules", interpretation_model: null, data_mode: "mock",
  };
}
function result(body: ResearchExecuteRequest): ResearchResult {
  const sentence = { text: "근거를 사용한 브리핑 초안입니다.", evidence_ids: ["F1"] };
  return { request_id: crypto.randomUUID(), question: body.question, conditions: body.conditions, data_mode: body.mode, source_name: "OpenDART · 금융감독원 전자공시", table_or_report: "연간 연결 재무제표",
    facts: [{ id: "F1", entity: body.conditions.entity, metric: "매출액", period: "2024", value: "1000", unit: "원", kind: "observation", source_urls: [], retrieved_at: "2026-09-17T00:00:00Z", formula: "원자료 값", details: { origin: "synthetic" } }],
    caveats: ["가상 자료는 실제 취재 근거로 사용할 수 없습니다."], cache: null,
    brief: { status: "complete", generation_method: body.briefing_method, model: body.briefing_method === "gemini" ? "gemini-test" : null, error: null, verification_status: "review_required", content: { summary: sentence, findings: [sentence], limitations: ["원인을 단정하지 않습니다."], follow_up_questions: ["추가로 확인할 자료는 무엇인가?"] } },
  };
}
function json(body: unknown) { return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }); }
function api() {
  return vi.mocked(fetch).mockImplementation(async (path, init) => {
    const body = JSON.parse(String(init?.body));
    if (path === "/api/v1/research/plan") return json({ ...plan(), question: body.question, data_mode: body.mode, interpretation_method: body.interpretation_method });
    expect(path).toBe("/api/v1/research/execute");
    expect(body.approved).toBe(true);
    return json(result(body));
  });
}
function enter() { render(<App />); fireEvent.click(screen.getByRole("button", { name: "2부 · 자유 질문과 AI 브리핑" })); }
async function propose() { fireEvent.click(screen.getByRole("button", { name: "조사 계획 제안받기" })); await screen.findByRole("heading", { name: "에이전트가 제안한 조사 계획" }); }
async function approve() { fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" })); return await screen.findByRole("region", { name: "이 결과의 실습 검토" }); }

test("Part 1 remains default; Part 2 proposes without evidence until explicit approval", async () => {
  const fetch = api(); render(<App />);
  expect(screen.getByRole("button", { name: "질문 분석" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "2부 · 자유 질문과 AI 브리핑" }));
  await propose();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("heading", { name: "취재 브리핑 초안" })).toBeNull();
  await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.getAllByRole("link", { name: "F1 근거 보기" })[0].getAttribute("href")).toBe("#research-F1");
  expect(screen.getByRole("region", { name: "이 결과의 실습 검토" }).textContent).toContain("기사 사용 승인이 아닙니다");
});

test("edited conditions are marked, hide results, and match final query conditions; review resets", async () => {
  const fetch = api(); enter(); await propose();
  const review = await approve(); fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  expect(within(review).getByRole("status").textContent).toContain("1/4");
  fireEvent.change(screen.getByRole("combobox", { name: "시작 연도" }), { target: { value: "2023" } });
  expect(screen.getByText("수정됨")).toBeTruthy(); expect(screen.queryByRole("table")).toBeNull();
  const nextReview = await approve();
  expect(within(nextReview).getByRole("status").textContent).toContain("0/4");
  const body = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body));
  expect(body.conditions.start_year).toBe(2023);
  expect(screen.getByText("2023~2024년")).toBeTruthy();
});

test("natural-language refinement sends the edited draft and requires another approval", async () => {
  const fetch = api(); enter(); await propose(); await approve();
  fireEvent.change(screen.getByRole("textbox", { name: "계획을 말로 수정하기" }), { target: { value: "최근 2년 매출만 봐줘" } });
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "수정 요청 반영" }));
  await screen.findByText("수정 요청을 반영한 계획입니다. 다시 확인하고 승인해 주세요.");
  expect(fetch).toHaveBeenCalledTimes(3);
  const body = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body));
  expect(body.revision).toBe("최근 2년 매출만 봐줘"); expect(body.previous_conditions.entity).toBe("SK하이닉스");
  expect(screen.queryByRole("table")).toBeNull();
});

test("unresolved unsupported scope displays Korean guidance and disables approval", async () => {
  const fetch = api(); fetch.mockResolvedValueOnce(json({ ...plan(), field_errors: { scope: "분기 실적은 아직 지원하지 않습니다." }, clarification_questions: ["연간 실적으로 조사 범위를 바꿔 주세요."] }));
  enter(); await propose(); expect(screen.getByText("분기 실적은 아직 지원하지 않습니다.")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("a late response cannot restore results after changing question or leaving Part 2", async () => {
  const fetch = api(); enter(); await propose();
  let resolve!: (r: Response) => void;
  fetch.mockImplementationOnce(async (_path, init) => new Promise<Response>(r => { resolve = r; expect(init?.signal).toBeTruthy(); }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  const body = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body));
  fireEvent.change(screen.getByRole("textbox", { name: "취재 질문 입력" }), { target: { value: "다른 질문" } });
  await act(async () => resolve(json(result(body))));
  expect(screen.queryByRole("table")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "1부 · 조건과 근거 확인" }));
  expect(screen.getByRole("button", { name: "질문 분석" })).toBeTruthy();
});

test("mismatched approved conditions are rejected without showing results", async () => {
  const fetch = api(); enter(); await propose();
  fetch.mockImplementationOnce(async (_path, init) => { const body = JSON.parse(String(init?.body)); body.conditions.entity = "다른 회사"; return json(result(body)); });
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("승인한 조건과 결과가 맞지 않습니다");
  expect(screen.queryByRole("table")).toBeNull();
});

test("failed Gemini briefing preserves evidence and is labeled as failed", async () => {
  const fetch = api(); enter(); await propose();
  fetch.mockImplementationOnce(async (_path, init) => { const body = JSON.parse(String(init?.body)); const response = result(body); response.brief = { ...response.brief, status: "failed", generation_method: "gemini", model: "gemini-test", content: null, error: "Gemini 브리핑의 근거 참조를 확인하지 못했습니다." }; return json(response); });
  await approve(); expect(screen.getByRole("alert").textContent).toContain("근거 참조를 확인하지 못했습니다");
  expect(screen.getByRole("table")).toBeTruthy(); expect(screen.queryByText("근거를 사용한 브리핑 초안입니다.")).toBeNull();
});

test("changing data or model mode clears plan and result; choosing live selects Gemini", async () => {
  api(); enter(); await propose(); await approve();
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "live" } });
  expect(screen.queryByRole("table")).toBeNull(); expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "계획·브리핑 작성 방식" }).value).toBe("gemini");
});
