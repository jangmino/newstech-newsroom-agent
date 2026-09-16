import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import { editableConditions } from "./conditions";
import { canCompareResults } from "./resultComparison";
import { examplePlan, exampleResult } from "./test/responses";
import type { ExecuteRequest, PlanRequest, PlanResponse, QueryMode, SnapshotMetadata } from "./types";

type Source = "kosis" | "opendart";

// Authored test responses; synthetic numbers, never recorded live API responses.
function metadata(source: Source): SnapshotMetadata {
  return {
    snapshot_id: `${source}-saved-test-v1`, source, title: `${source} 저장 자료`,
    captured_at: "2026-09-16T00:00:00Z", unit: source === "kosis" ? "%" : "원",
    coverage: source === "kosis" ? "15~29세 · 17개 시도 · 2020~2024년" : "삼성전자 · 2022·2024년 연간 연결 매출액",
    source_urls: source === "kosis"
      ? ["https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7015S"]
      : ["https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250101002022"],
    caveats: ["확보 이후 개정·정정을 반영하지 않은 공식 저장 자료입니다. 사람 검토가 필요합니다."],
  };
}

function planned(source: Source, mode: QueryMode = "snapshot"): PlanResponse {
  const plan = examplePlan(source);
  plan.data_mode = mode;
  plan.snapshot = mode === "snapshot" ? metadata(source) : null;
  plan.field_options.metric = [source === "kosis" ? "고용률" : "매출액"];
  if (source === "kosis") plan.field_options["filters.age_range"] = ["15-29세"];
  else {
    plan.field_options["filters.statement_basis"] = ["연결"];
    plan.query_plan.period = "2022-2024";
    plan.available_years = [2022, 2024];
  }
  return plan;
}

function resultFor(source: Source, request: ExecuteRequest) {
  const result = exampleResult(planned(source, request.mode), request.conditions);
  result.evidence.data_mode = request.mode;
  result.evidence.source_name = source === "kosis" ? "KOSIS 공식 자료" : "OpenDART 공식 자료";
  result.evidence.table_or_report = "저장한 공식 자료";
  result.evidence.caveats = metadata(source).caveats;
  result.snapshot = request.mode === "snapshot" ? metadata(source) : null;
  result.brief.summary = "저장 자료 기준으로 승인한 조건을 비교했습니다.";
  if (source === "kosis") {
    result.calculation!.data_origin = "kosis";
    result.calculation!.rows[0].region = "서울특별시";
    result.evidence.raw_values = [{ region: "서울특별시", region_code: "11", year: 2024,
      value: "48", raw_value: "48", unit: "%", org_id: "101", table_id: "DT_1DA7015S",
      item_id: "T90", age_code: "75", period_code: "A", last_changed_at: "2026-06-29" }];
  } else {
    result.financial_calculation = {
      data_origin: "opendart", start_year: 2022, end_year: 2024, start_value: "100", end_value: "120",
      input_unit: "원", result_unit: "원", change: "20", decimal_places: 0, status: "calculated", reason: null,
    };
    result.evidence.raw_values = [2022, 2024].map((year) => ({
      year, value: year === 2022 ? "100" : "120", raw_amount: year === 2022 ? "100" : "120",
      receipt_no: `2025010100${year}`, retrieved_at: metadata(source).captured_at, currency: "KRW",
    }));
  }
  return result;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function setup(source: Source = "kosis", mode: QueryMode = "snapshot") {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === "/api/v1/plan") {
      const request = JSON.parse(String(init?.body)) as PlanRequest;
      const response = planned(source, request.mode);
      if (request.conditions) {
        response.query_plan = { ...response.query_plan, ...request.conditions };
        response.conditions_preserved = true;
      }
      return json(response);
    }
    expect(path).toBe("/api/v1/execute");
    const request = JSON.parse(String(init?.body)) as ExecuteRequest;
    expect(request.approved).toBe(true);
    if (request.mode === "snapshot") expect(request.snapshot_id).toBe(metadata(source).snapshot_id);
    return json(resultFor(source, request));
  });
  render(<App />);
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: mode } });
  if (source === "opendart") fireEvent.click(screen.getByRole("button", { name: "삼성전자의 최근 실적은 악화됐는가?" }));
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

test.each(["kosis", "opendart"] as const)("%s preview discloses origin without data; approval shows saved results", async (source) => {
  const fetch = setup(source);
  expect(fetch).not.toHaveBeenCalled();
  await plan();
  const preview = screen.getByLabelText("승인 전 저장 자료 안내");
  expect(within(preview).getByText("공식 저장 자료 · 최신 조회 아님")).toBeTruthy();
  expect(within(preview).getByText(/원래 조회 시각/).textContent)
    .toContain(new Date(metadata(source).captured_at).toLocaleString("ko-KR"));
  expect(within(preview).getByRole("link").getAttribute("href")).toBe(metadata(source).source_urls[0]);
  expect(within(preview).getByText(/지원 범위/).textContent).toContain(metadata(source).coverage);
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  const review = await approve();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.queryByLabelText("승인 전 저장 자료 안내")).toBeNull();
  expect(screen.queryByText(/아직 자료와 브리핑을 표시하지 않았습니다/)).toBeNull();
  expect(screen.getByText(/저장 자료 확인과 계산 완료가 사실 검증 완료나 기사 사용 승인을 뜻하지 않습니다/)).toBeTruthy();
  const grounded = screen.getByRole("article", { name: "근거 기반 브리핑" });
  expect(within(grounded).getByText(/공식 저장 자료 기반 브리핑/)).toBeTruthy();
  expect(screen.getByRole("table", { name: source === "kosis"
    ? "15~29세 연간 고용률 · KOSIS 공식 저장 자료"
    : "삼성전자 연간 연결 매출액 · OpenDART 공식 저장 자료" })).toBeTruthy();
  expect(screen.queryByText(/공식 통계 실제 조회|공식 공시 실제 조회|가상 수치 계산/)).toBeNull();
  expect(screen.queryByLabelText("공식 자료 재사용 안내")).toBeNull();
  for (const checkbox of within(review).getAllByRole("checkbox")) fireEvent.click(checkbox);
  expect(within(review).getByRole("status").textContent).toContain("4/4");
  expect(within(review).getByText(/사실 검증 완료나 기사 사용 승인이 아닙니다/)).toBeTruthy();
  expect(within(review).getByText(/원래 조회 시각·지원 범위와 확보 이후/)).toBeTruthy();
});

test("live error preserves edits; selecting snapshot only prepares and requires reapproval", async () => {
  const fetch = setup("kosis", "live");
  await plan();
  const oldReview = await approve();
  fireEvent.click(within(oldReview).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "대상" }), { target: { value: "수도권 시·도" } });
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2021-2024" } });
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  fetch.mockResolvedValueOnce(json({ detail: {
    code: "public_data_busy", message: "현재 실제 자료 조회 요청이 많습니다.", field_errors: {},
  } }, 429));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toContain("조회 요청이 많습니다");
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "조회 자료" }).value).toBe("live");
  expect(fetch).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("button", { name: "저장 자료로 조건 다시 확인" }));
  await screen.findByLabelText("승인 전 저장 자료 안내");
  expect(fetch).toHaveBeenCalledTimes(4);
  const prepared = JSON.parse(String(fetch.mock.calls[3][1]?.body)) as PlanRequest;
  expect(prepared.mode).toBe("snapshot");
  expect(prepared.interpretation_method).toBe("mock_rules");
  expect(prepared.conditions).toMatchObject({ entity: "수도권 시·도", period: "2021-2024", comparison: "증감률" });
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2021-2024");
  expect(screen.getByText(/전환하기 전 실제 조회 안내/).textContent).toContain("조회 요청이 많습니다");
  expect(screen.getByText(/기존 입력 조건을 유지했습니다/)).toBeTruthy();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  const review = await approve();
  expect(fetch).toHaveBeenCalledTimes(5);
  const executed = JSON.parse(String(fetch.mock.calls[4][1]?.body)) as ExecuteRequest;
  expect(executed.conditions).toEqual(prepared.conditions);
  expect(within(review).getByRole("status").textContent).toContain("0/4");
  expect(screen.queryByRole("article", { name: "이전 승인 결과" })).toBeNull();
});

test("snapshot condition edits hide results and reapproval compares saved results with fresh review", async () => {
  setup();
  await plan();
  const review = await approve();
  fireEvent.click(within(review).getAllByRole("checkbox")[0]);
  fireEvent.change(screen.getByRole("combobox", { name: "비교 기준" }), { target: { value: "증감률" } });
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByLabelText("이 결과의 저장 자료 안내")).toBeNull();
  expect(screen.getByLabelText("승인 전 저장 자료 안내")).toBeTruthy();
  expect(screen.getByText("참가자가 조건을 수정했습니다.", { exact: false })).toBeTruthy();
  const retried = await approve();
  expect(within(retried).getByRole("status").textContent).toContain("0/4");
  expect(screen.getByRole("table", { name: "시도별 결과 비교 · KOSIS 공식 저장 자료" })).toBeTruthy();
  const previous = screen.getByRole("article", { name: "이전 승인 결과" });
  expect(within(previous).getByText("공식 저장 자료 · 최신 조회 아님")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "질문 입력" }), { target: { value: "다른 고용 질문" } });
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
  expect(screen.queryByLabelText("승인 전 저장 자료 안내")).toBeNull();
});

test.each(["mode", "id", "source", "time", "evidence_time", "missing", "cache"])("mismatched snapshot %s never appears as an approved result", async (change) => {
  const fetch = setup();
  await plan();
  const result = resultFor("kosis", { question: "청년 고용률", mode: "snapshot", approved: true,
    conditions: editableConditions(planned("kosis").query_plan) });
  if (change === "mode") result.evidence.data_mode = "live";
  if (change === "id") result.snapshot!.snapshot_id = "another-version";
  if (change === "source") result.snapshot!.source = "opendart";
  if (change === "time") result.snapshot!.captured_at = "2026-09-17T00:00:00Z";
  if (change === "evidence_time") result.evidence.retrieved_at = "2026-09-17T00:00:00Z";
  if (change === "missing") result.snapshot = null;
  if (change === "cache") result.cache = { status: "hit", scope: "process", stored_at: "", expires_at: "", ttl_seconds: 10, age_seconds: 1 };
  fetch.mockResolvedValueOnce(json(result));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("region", { name: "이 결과의 실습 검토" })).toBeNull();
});

test.each(["snapshot_changed", "snapshot_disabled", "snapshot_unavailable"])("%s keeps conditions and never substitutes data", async (code) => {
  const fetch = setup();
  await plan();
  await approve();
  fetch.mockResolvedValueOnce(json({ detail: {
    code, message: "저장 자료 안내를 다시 확인해 주세요.", field_errors: {},
  } }, code === "snapshot_changed" ? 409 : 503));
  fireEvent.click(screen.getByRole("button", { name: "이 조건으로 조회" }));
  expect((await screen.findByRole("alert")).textContent).toBe("저장 자료 안내를 다시 확인해 주세요.");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "기간" }).value).toBe("2020-2024");
  expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "조회 자료" }).value).toBe("snapshot");
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each(["plan", "execute"])("late snapshot %s is ignored after switching data mode", async (stage) => {
  const fetch = setup();
  if (stage === "execute") await plan();
  let finish!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: stage === "plan" ? "질문 분석" : "이 조건으로 조회" }));
  fireEvent.change(screen.getByRole("combobox", { name: "조회 자료" }), { target: { value: "mock" } });
  await act(async () => finish(json(stage === "plan" ? planned("kosis") : resultFor("kosis", {
    question: "청년 고용률", mode: "snapshot", approved: true,
    conditions: editableConditions(planned("kosis").query_plan),
  }))));
  expect(screen.queryByLabelText("승인 전 저장 자료 안내")).toBeNull();
  expect(screen.queryByRole("article", { name: "근거 기반 브리핑" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("unsupported saved-data period blocks approval", async () => {
  const fetch = setup("opendart");
  await plan();
  fireEvent.change(screen.getByRole("textbox", { name: "기간" }), { target: { value: "2022-2023" } });
  expect(screen.getByText(/저장된 매출액 실습은/)).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "이 조건으로 조회" }).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("unsafe preview source link cannot enable approval", async () => {
  const fetch = setup();
  const response = planned("kosis");
  response.snapshot!.source_urls = ["https://invalid.test/private"];
  fetch.mockResolvedValueOnce(json(response));
  fireEvent.click(screen.getByRole("button", { name: "질문 분석" }));
  expect((await screen.findByRole("alert")).textContent).toContain("출처와 시각을 확인하지 못했습니다");
  expect(screen.queryByRole("button", { name: "이 조건으로 조회" })).toBeNull();
});

test("different snapshot versions cannot be compared as condition changes", () => {
  const request: ExecuteRequest = { question: "청년 고용률", mode: "snapshot", approved: true,
    conditions: editableConditions(planned("kosis").query_plan) };
  const before = resultFor("kosis", request);
  const after = resultFor("kosis", { ...request, conditions: { ...request.conditions, comparison: "증감률" } });
  expect(canCompareResults(before, after)).toBe(true);
  after.snapshot!.snapshot_id = "a-new-version";
  expect(canCompareResults(before, after)).toBe(false);
  after.snapshot = null;
  expect(canCompareResults(before, after)).toBe(false);
});
