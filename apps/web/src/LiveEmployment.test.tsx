import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import { editableConditions } from "./conditions";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, ExecutionResponse, PlanResponse } from "./types";

const question = "전국 시·도 15-29세 청년 고용률 2020-2024년 연간 증감 폭 비교";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function livePlan(): PlanResponse {
  const plan = examplePlan();
  plan.question = question;
  plan.data_mode = "live";
  plan.field_options.metric = ["고용률"];
  plan.field_options["filters.age_range"] = ["15-29세"];
  plan.query_plan.selection_reason = "청년 고용의 변화를 확인하기 위해 KOSIS를 선택했습니다.";
  return plan;
}

function liveResult(request: ExecuteRequest): ExecutionResponse {
  // Authored UI test numbers. These are not recordings or verified official observations.
  const result = exampleResult(livePlan(), request.conditions);
  const [start, end] = request.conditions.period.split("-").map(Number);
  const relative = request.conditions.comparison === "증감률";
  result.evidence.data_mode = "live";
  result.evidence.source_name = "KOSIS · 국가데이터처 경제활동인구조사";
  result.evidence.table_or_report = "행정구역(시도)/연령별 경제활동인구 · 15~29세 연간 고용률";
  result.evidence.caveats = ["표본오차와 지역 경계를 확인해 주세요."];
  result.evidence.query_parameters = { ...result.evidence.query_parameters,
    "filters.age_range": request.conditions.filters.age_range, "filters.frequency": "연간" };
  result.evidence.raw_values = [start, end].map((year) => ({
    region: "서울특별시", region_code: "11", year, value: year === start ? "40" : "48",
    raw_value: year === start ? "40" : "48", unit: "%", org_id: "101", table_id: "DT_1DA7015S",
    age_code: "75", item_id: "T90", period_code: "A", last_changed_at: "2026-06-29",
    retrieved_at: "2026-09-16T00:00:00Z", source_url: "https://invalid.test/untrusted-link",
  }));
  result.brief.summary = "승인한 시도의 고용률 변화입니다.";
  result.brief.interpretation_limits = ["순위가 정책 효과나 통계적 유의성을 뜻하지 않습니다."];
  result.calculation = {
    dataset_id: "kosis-test", data_origin: "kosis", start_year: start, end_year: end,
    input_unit: "%", result_unit: relative ? "%" : "%p", decimal_places: 2,
    ranking_method: "반올림 전 변화값 내림차순", warnings: [],
    rows: [{ region: "서울특별시", start_value: "40", end_value: "48",
      change: relative ? "20.00" : "8.00", rank: 1, status: "calculated", reason: null }],
  };
  return result;
}

function setup() {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") return json(livePlan());
    expect(path).toBe("/api/v1/execute");
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(request.mode).toBe("live");
    expect(request.approved).toBe(true);
    return json(liveResult(request));
  });
  render(<App />);
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "live" } });
  fireEvent.change(screen.getByRole("textbox", { name: "질문 입력" }), { target: { value: question } });
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

test("KOSIS planning has no evidence; approval reflects edits and shows source metadata", async () => {
  const fetch = setup();
  expect(fetch).not.toHaveBeenCalled();
  await plan();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("link", { name: /KOSIS 원표/ })).toBeNull();
  expect(screen.queryByRole("option", { name: "15-34세" })).toBeNull();
  expect(screen.queryByRole("option", { name: "취업자 수" })).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "대상" }), { target: { value: "수도권 시·도" } });
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2021-2024" } });
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.getByText("참가자가 조건을 수정했습니다.", { exact: false })).toBeTruthy();
  await approve();
  const request = JSON.parse(String(fetch.mock.calls.at(-1)?.[1]?.body)) as ExecuteRequest;
  expect(request.conditions).toMatchObject({ entity: "수도권 시·도", period: "2021-2024", comparison: "증감률" });
  const evidence = screen.getByRole("region", { name: "KOSIS · 국가데이터처 경제활동인구조사" });
  expect(within(evidence).getByText("수도권 시·도")).toBeTruthy();
  expect(within(evidence).getByText("2021-2024")).toBeTruthy();
  expect(within(evidence).getByText("입력 % · 결과 %")).toBeTruthy();
  expect(within(evidence).getByText("20.00")).toBeTruthy();
  expect(within(evidence).getByText("자료 조회 완료 시각")).toBeTruthy();
  expect(within(evidence).getByText("자료 최종수정일: 2026-06-29")).toBeTruthy();
  expect(within(evidence).getByRole("link", { name: /KOSIS 원표/ }).getAttribute("href"))
    .toBe("https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7015S");
  fireEvent.click(within(evidence).getByText("연간 원자료 2개 값과 통계 코드 확인"));
  expect(within(evidence).getByRole("table", { name: /15~29세 연간 고용률/ })).toBeTruthy();
  expect(within(evidence).queryByText(/가상|공식 통계 아님/)).toBeNull();
  expect(screen.getByText("모의 예시 · 미리 작성한 응답")).toBeTruthy();
  expect(screen.getByText("KOSIS 원표·통계 코드·실제 조회 시각과 자료 최종수정일을 확인했습니다.")).toBeTruthy();
});

test("ambiguous or unsupported conditions remain blank until participant chooses supported values", async () => {
  const fetch = setup();
  const unresolved = livePlan();
  unresolved.query_plan.metric = "";
  unresolved.query_plan.filters.age_range = "";
  unresolved.query_plan.clarification_required = true;
  unresolved.query_plan.clarification_questions = ["실제 자료는 15~29세 고용률만 지원합니다."];
  unresolved.required_fields = ["metric", "filters.age_range"];
  fetch.mockResolvedValueOnce(json(unresolved));
  await plan();
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "청년 연령 범위" }).value).toBe("");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  fireEvent.change(screen.getByRole("combobox", { name: "지표" }), { target: { value: "고용률" } });
  fireEvent.change(screen.getByRole("combobox", { name: "청년 연령 범위" }), { target: { value: "15-29세" } });
  expect(fetch).toHaveBeenCalledTimes(1);
  await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("unsupported KOSIS period blocks approval with the statistical scope", async () => {
  const fetch = setup();
  await plan();
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2020-2025" } });
  expect(screen.getByText(/실제 청년 고용 자료는 2020~2024년만 지원/)).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("condition edits hide all results and reset review; reapproval compares official statistics", async () => {
  setup();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.queryByRole("region", { name: "KOSIS 통계 출처와 연간 원자료" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  const next = await approve();
  expect(within(next).getByRole("status").textContent).toBe("실습 검토 전 · 0/4개 확인");
  expect(screen.getByRole("table", { name: "시도별 결과 비교 · KOSIS 실제 조회" })).toBeTruthy();
  expect(screen.queryByRole("table", { name: /가상 지역별/ })).toBeNull();
});

test.each(["question", "mode"])("changing %s clears result and ignores a late KOSIS response", async (change) => {
  const fetch = setup();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect(screen.getByRole("button", { name: "통계 자료를 조회하는 중…" })).toBeTruthy();
  if (change === "question") {
    fireEvent.change(screen.getByRole("textbox", { name: "질문 입력" }), { target: { value: "다른 청년 질문" } });
  } else {
    fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "mock" } });
  }
  await act(async () => finish(json(liveResult({ question, mode: "live", approved: true,
    conditions: editableConditions(livePlan().query_plan) }))));
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test("KOSIS error keeps conditions, hides old values, and does not retry or show mock fallback", async () => {
  const fetch = setup();
  await plan();
  await approve();
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "kosis_no_data", message: "선택한 조건의 고용률 자료가 없습니다.", field_errors: {},
  } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("고용률 자료가 없습니다");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("link", { name: /KOSIS 원표/ })).toBeNull();
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(fetch).toHaveBeenCalledTimes(3);
  await approve();
  expect(screen.getByText("실습 검토 전 · 0/4개 확인", { selector: "p" })).toBeTruthy();
});

test.each(["mode", "origin", "source"])("mismatched %s cannot be shown as approved KOSIS data", async (change) => {
  const fetch = setup();
  await plan();
  const result = liveResult({ question, mode: "live", approved: true,
    conditions: editableConditions(livePlan().query_plan) });
  if (change === "mode") result.evidence.data_mode = "mock";
  if (change === "origin") result.calculation!.data_origin = "synthetic";
  if (change === "source") result.query_plan.selected_source = "opendart";
  fetch.mockResolvedValueOnce(json(result));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("자료 모드를 확인하지 못했습니다");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
});

test("checking every official result review item is not article approval", async () => {
  setup();
  await plan();
  const review = await approve();
  for (const checkbox of within(review).getAllByRole("checkbox")) fireEvent.click(checkbox);
  expect(within(review).getByRole("status").textContent).toBe("실습 검토 항목 확인 완료 · 4/4개 확인");
  expect(within(review).getByText(/사실 검증 완료나 기사 사용 승인이 아닙니다/)).toBeTruthy();
  expect(within(review).getByText(/공식 통계도 원표·표본오차·지역 경계와 해석 검토가 필요/)).toBeTruthy();
});

const cacheMetadata = {
  scope: "process" as const, stored_at: "2026-09-16T00:00:00Z",
  expires_at: "2026-09-16T01:00:00Z", ttl_seconds: 3600, age_seconds: 20,
};

test.each([
  ["miss", "공식 자료를 새로 조회했습니다."],
  ["hit", "보관된 공식 자료를 재사용했습니다."],
  ["coalesced", "같은 조건의 진행 중 조회 결과를 함께 사용했습니다."],
] as const)("%s explains data reuse only after approval and retains original time", async (status, label) => {
  const fetch = setup();
  await plan();
  expect(screen.queryByLabelText("공식 자료 재사용 안내")).toBeNull();
  const result = liveResult({ question, mode: "live", approved: true,
    conditions: editableConditions(livePlan().query_plan) });
  result.evidence.retrieved_at = "2026-09-15T23:59:59Z";
  result.cache = { ...cacheMetadata, status };
  fetch.mockResolvedValueOnce(json(result));
  const review = await approve();
  const evidence = screen.getByRole("region", { name: "KOSIS · 국가데이터처 경제활동인구조사" });
  const notice = within(evidence).getByLabelText("공식 자료 재사용 안내");
  expect(within(notice).getByText(label)).toBeTruthy();
  expect(within(notice).getByText(`원자료 조회 시각: ${new Date(result.evidence.retrieved_at).toLocaleString("ko-KR")}`)).toBeTruthy();
  expect(within(notice).getByText(`재사용 기한: ${new Date(cacheMetadata.expires_at).toLocaleString("ko-KR")}`)).toBeTruthy();
  if (status === "hit") {
    expect(within(notice).getByText(/외부 API를 다시 호출하지 않았습니다/)).toBeTruthy();
    expect(screen.queryByText("승인한 조건으로 실제 조회했습니다.", { exact: false })).toBeNull();
    expect(screen.getByText(/이전에 조회해 보관한 KOSIS/)).toBeTruthy();
  }
  expect(within(notice).getByText(/다음 승인 때 새로 조회/)).toBeTruthy();
  expect(within(review).getByText(/자료 재사용 여부와 원래 조회 시각·재사용 기한/)).toBeTruthy();
  expect(within(review).getByRole("status").textContent).toContain("0/4");
});

test("cached reapproval recalculates, compares acquisition status, and resets review", async () => {
  const fetch = setup();
  let count = 0;
  fetch.mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") return json(livePlan());
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    const result = liveResult(request);
    result.cache = { ...cacheMetadata, status: count++ ? "hit" : "miss" };
    return json(result);
  });
  await plan();
  const firstReview = await approve();
  for (const check of within(firstReview).getAllByRole("checkbox")) fireEvent.click(check);
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.queryByLabelText("공식 자료 재사용 안내")).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  const review = await approve();
  expect(fetch).toHaveBeenCalledTimes(3); // A cache hit still requires an explicit /execute approval.
  expect(within(review).getByRole("status").textContent).toContain("0/4");
  const previous = screen.getByRole("article", { name: "이전 승인 결과" });
  const current = screen.getByRole("article", { name: "이번 승인 결과" });
  expect(within(previous).getByText("공식 자료를 새로 조회했습니다.")).toBeTruthy();
  expect(within(current).getByText("보관된 공식 자료를 재사용했습니다.")).toBeTruthy();
  const evidence = screen.getByRole("region", { name: "KOSIS · 국가데이터처 경제활동인구조사" });
  expect(within(evidence).getByText("증감률")).toBeTruthy();
  expect(within(evidence).getByText("20.00")).toBeTruthy();
  // A later failed refresh cannot restore the cached result or its review state.
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "kosis_unavailable", message: "KOSIS 자료를 가져오지 못했습니다.", field_errors: {},
  } }, 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("공식 자료 재사용 안내")).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
});

test.each([
  ["public_data_rate_limited", 23, "현재 서버의 KOSIS 조회 요청 한도에 도달했습니다."],
  ["public_data_busy", null, "현재 서버에서 KOSIS 자료를 조회하는 요청이 많습니다."],
] as const)("%s retains edits, hides results, and requires explicit reapproval", async (code, seconds, message) => {
  const fetch = setup();
  await plan();
  const firstReview = await approve();
  fireEvent.click(within(firstReview).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  fetch.mockResolvedValueOnce(json({ detail: {
    code, message: `${message} 입력한 조건은 유지됩니다. 자동으로 다시 조회하지 않습니다. 잠시 후 ‘이 조건으로 조회’를 다시 눌러 주세요.`,
    field_errors: {}, source: "kosis", scope: "process", retry_after_seconds: seconds,
  } }, 429));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(message);
  expect(alert.textContent).toContain("자동으로 다시 조회하지 않습니다");
  if (seconds) {
    expect(alert.textContent).toContain("약 23초 뒤");
    expect(alert.textContent).toContain("다른 요청에 따라 달라질 수 있습니다");
  } else {
    expect(alert.textContent).not.toContain("초 뒤");
  }
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "비교 기준" }).value).toBe("증감률");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(screen.getByText("참가자가 조건을 수정했습니다.", { exact: false })).toBeTruthy();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByRole("article", { name: "이전 승인 결과" })).toBeNull();
  expect(screen.queryByLabelText("공식 자료 재사용 안내")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(3);
  // Advance beyond the suggested wait: no timer submits an approval on the participant's behalf.
  vi.useFakeTimers();
  try {
    await act(async () => vi.advanceTimersByTimeAsync(61_000));
    expect(fetch).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
  const review = await approve();
  expect(fetch).toHaveBeenCalledTimes(4);
  expect(within(review).getByRole("status").textContent).toContain("0/4");
  expect(screen.queryByRole("alert")).toBeNull();
});

test.each([0, -1, 1.5, 61, "30", null])("invalid wait hint %s is not displayed", async (seconds) => {
  const fetch = setup();
  await plan();
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "public_data_rate_limited", message: "잠시 후 다시 조회해 주세요.",
    field_errors: {}, retry_after_seconds: seconds,
  } }, 429));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toBe("잠시 후 다시 조회해 주세요.");
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("editing a condition ignores a late limit error and does not start another request", async () => {
  const fetch = setup();
  await plan();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2021-2024" } });
  await act(async () => finish(json({ detail: {
    code: "public_data_busy", message: "잠시 후 다시 조회해 주세요.", field_errors: {},
  } }, 429)));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(2);
});
