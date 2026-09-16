import { FormEvent, useEffect, useRef, useState } from "react";
import {
  conditionErrors, conditionLabels, conditionValue, editableConditions, sourceLabel, updateCondition,
} from "./conditions";
import { ReviewSession } from "./ReviewSession";
import { FinancialEvidence } from "./FinancialEvidence";
import { KosisEvidence } from "./KosisEvidence";
import { CacheNotice, cacheLabel } from "./CacheNotice";
import { SnapshotNotice, validSnapshot } from "./SnapshotNotice";
import { CalculationTable } from "./CalculationTable";
import { ConditionComparison } from "./ConditionComparison";
import { canCompareResults } from "./resultComparison";
import { WorkshopGuide } from "./WorkshopGuide";
import { workshopQuestion, type WorkshopScenarioId } from "./workshopScenarios";
import { getJson, postJson, type ApiGet, type ApiPost } from "./api";
import { OperationsPanel } from "./OperationsPanel";
import type {
  ExecutionResponse, InterpretationMethod, PlanResponse,
  QueryConditions, QueryMode,
} from "./types";

const samples = [
  workshopQuestion,
  "삼성전자의 최근 실적은 악화됐는가?",
];

function App({ post = postJson, get = getJson }: { post?: ApiPost; get?: ApiGet }) {
  const [question, setQuestion] = useState(samples[0]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [draft, setDraft] = useState<QueryConditions | null>(null);
  const [result, setResult] = useState<ExecutionResponse | null>(null);
  const [previousResult, setPreviousResult] = useState<ExecutionResponse | null>(null);
  // Retain one success for comparison, hidden until a new approval succeeds.
  const lastSuccessfulResult = useRef<ExecutionResponse | null>(null);
  const [busy, setBusy] = useState<"plan" | "execute" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const [guide, setGuide] = useState<WorkshopScenarioId | null>(null);
  const [interpretationMethod, setInterpretationMethod] = useState<InterpretationMethod>("mock_rules");
  const [dataMode, setDataMode] = useState<QueryMode>("mock");
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => {
    revision.current += 1;
    controller.current?.abort();
  }, []);

  function invalidate() {
    revision.current += 1;
    controller.current?.abort();
    setResult(null);
    setPreviousResult(null);
    setBusy(null);
    setError(null);
  }

  function changeQuestion(value: string) {
    invalidate();
    setFallbackReason(null);
    lastSuccessfulResult.current = null;
    setQuestion(value);
    setPlan(null);
    setDraft(null);
    setGuide(null);
  }

  function startGuide(id: WorkshopScenarioId) {
    setDataMode("mock");
    changeQuestion(workshopQuestion);
    setGuide(id);
  }

  function changeDataMode(value: QueryMode) {
    changeQuestion(question);
    setDataMode(value);
  }

  function changeInterpretationMethod(value: InterpretationMethod) {
    invalidate();
    setFallbackReason(null);
    lastSuccessfulResult.current = null;
    setPlan(null);
    setDraft(null);
    setInterpretationMethod(value);
  }

  function applyGuideConditions(conditions: QueryConditions) {
    if (!guide || busy || plan?.query_plan.selected_source !== "kosis" || !draft) return;
    invalidate();
    setDraft({ ...conditions, filters: { ...conditions.filters } });
  }

  function changeCondition(field: string, value: string) {
    if (!draft) return;
    invalidate();
    setDraft(updateCondition(draft, field, value));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    invalidate();
    setFallbackReason(null);
    lastSuccessfulResult.current = null;
    setPlan(null);
    setDraft(null);
    if (question.trim().length < 3 || question.trim().length > 1000) {
      setError("질문을 3자 이상 1,000자 이하로 입력해 주세요.");
      return;
    }
    const current = revision.current;
    const request = new AbortController();
    controller.current = request;
    setBusy("plan");
    try {
      const response = await post<PlanResponse>("/api/v1/plan", {
        question: question.trim(), mode: dataMode, interpretation_method: interpretationMethod,
      }, request.signal);
      if (current !== revision.current) return;
      if (response.data_mode !== dataMode) throw new Error("조회 자료 모드가 일치하지 않습니다. 다시 분석해 주세요.");
      if (dataMode === "snapshot" && response.query_plan.selected_source !== "undetermined"
        && !validSnapshot(response.snapshot, response.query_plan.selected_source)) {
        throw new Error("저장 자료의 출처와 시각을 확인하지 못했습니다. 다시 분석해 주세요.");
      }
      setPlan(response);
      setDraft(editableConditions(response.query_plan));
    } catch (caught) {
      if (current === revision.current) {
        setError(caught instanceof Error ? caught.message : "질문을 다시 해석해 주세요.");
      }
    } finally {
      if (current === revision.current) setBusy(null);
    }
  }

  async function prepareSnapshot() {
    if (!plan || !draft || !error || busy || plan.data_mode !== "live") return;
    const conditions = { ...draft, filters: { ...draft.filters } };
    const originalQuestion = plan.question;
    setFallbackReason(error);
    invalidate();
    lastSuccessfulResult.current = null;
    setPlan(null);
    setDraft(null);
    setGuide(null);
    setDataMode("snapshot");
    setInterpretationMethod("mock_rules");
    const current = revision.current;
    const request = new AbortController();
    controller.current = request;
    setBusy("plan");
    try {
      const response = await post<PlanResponse>("/api/v1/plan", {
        question: originalQuestion, mode: "snapshot", interpretation_method: "mock_rules", conditions,
      }, request.signal);
      if (current !== revision.current) return;
      if (response.data_mode !== "snapshot" || !response.conditions_preserved
        || !validSnapshot(response.snapshot, conditions.selected_source)
        || response.query_plan.selected_source !== conditions.selected_source) {
        throw new Error("저장 자료의 조건과 출처를 확인하지 못했습니다. 다시 분석해 주세요.");
      }
      setPlan(response);
      setDraft(editableConditions(response.query_plan));
    } catch (caught) {
      if (current === revision.current) setError(caught instanceof Error ? caught.message : "저장 자료 안내를 확인하지 못했습니다.");
    } finally {
      if (current === revision.current) setBusy(null);
    }
  }

  async function approve(event: FormEvent) {
    event.preventDefault();
    if (!plan || !draft || busy) return;
    const errors = conditionErrors(plan, draft);
    if (errors.length > 0) {
      setError(errors.join(" "));
      return;
    }
    invalidate();
    const current = revision.current;
    const request = new AbortController();
    controller.current = request;
    setBusy("execute");
    const conditions = { ...draft, period: draft.period.trim(), filters: { ...draft.filters } };
    try {
      if (plan.data_mode === "snapshot" && !validSnapshot(plan.snapshot, conditions.selected_source)) {
        throw new Error("저장 자료 안내를 다시 확인한 뒤 승인해 주세요.");
      }
      const response = await post<ExecutionResponse>("/api/v1/execute", {
        question: plan.question, mode: plan.data_mode, approved: true, conditions,
        ...(plan.data_mode === "snapshot" ? { snapshot_id: plan.snapshot!.snapshot_id } : {}),
      }, request.signal);
      if (current !== revision.current) return;
      if (!response.general_response?.text || response.general_response.data_mode !== "mock"
        || response.general_response.generation_method !== "scripted") {
        throw new Error("응답 비교를 준비하지 못했습니다. 잠시 후 다시 조회해 주세요.");
      }
      if (response.evidence.data_mode !== plan.data_mode
        || response.query_plan.selected_source !== conditions.selected_source
        || (plan.data_mode !== "mock" && (conditions.selected_source === "kosis"
          ? response.calculation?.data_origin !== "kosis" || response.financial_calculation !== null
          : !response.financial_calculation || response.financial_calculation.data_origin !== "opendart"))) {
        throw new Error("조회 자료 모드를 확인하지 못했습니다. 다시 조회해 주세요.");
      }
      if (plan.data_mode === "snapshot" && (!validSnapshot(response.snapshot, conditions.selected_source)
        || response.snapshot.snapshot_id !== plan.snapshot?.snapshot_id
        || response.snapshot.captured_at !== plan.snapshot.captured_at
        || Date.parse(response.evidence.retrieved_at) !== Date.parse(response.snapshot.captured_at)
        || response.cache !== null)) {
        throw new Error("승인한 저장 자료의 버전과 시각이 일치하지 않습니다. 다시 분석해 주세요.");
      }
      setDraft(conditions);
      const previous = lastSuccessfulResult.current;
      setPreviousResult(previous && canCompareResults(previous, response) ? previous : null);
      lastSuccessfulResult.current = response;
      setResult(response);
    } catch (caught) {
      if (current === revision.current) {
        setError(caught instanceof Error ? caught.message : "조건을 확인한 뒤 다시 시도해 주세요.");
      }
    } finally {
      if (current === revision.current) setBusy(null);
    }
  }

  const fields = plan ? ["entity", "metric", "period", "comparison",
    ...Object.keys(plan.field_options).filter((field) => field.startsWith("filters."))] : [];
  const original = plan ? editableConditions(plan.query_plan) : null;
  const modifiedFields = draft && original
    ? fields.filter((field) => conditionValue(draft, field) !== conditionValue(original, field)) : [];
  const errors = plan && draft ? conditionErrors(plan, draft) : [];

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NewsTech Initiatives 2026 · 실습용 프로토타입</p>
          <h1>뉴스룸 데이터 에이전트</h1>
        </div>
        <span className="mode">{dataMode === "snapshot" ? "공식 저장 자료" : dataMode === "live" ? "공식 실제 자료" : "모의 자료 모드"}</span>
      </header>

      <OperationsPanel get={get} />

      <section className="question-panel" aria-labelledby="question-title" aria-busy={busy === "plan"}>
        <div className="section-heading">
          <span>01</span>
          <div>
            <h2 id="question-title">취재 질문</h2>
            <p>에이전트가 어떤 공식 자료와 조건을 선택하는지 확인해 보세요.</p>
          </div>
        </div>
        <div className="sample-list" aria-label="실습 질문 예시">
          {samples.map((sample) => (
            <button key={sample} type="button" onClick={() => changeQuestion(sample)}>{sample}</button>
          ))}
        </div>
        <div className="interpretation-choice">
          <label htmlFor="data-mode">조회 자료</label>
          <select id="data-mode" value={dataMode} aria-describedby="data-mode-help"
            onChange={(event) => changeDataMode(event.target.value as QueryMode)}>
            <option value="mock">모의 자료 · 두 실습 질문</option>
            <option value="live">공식 실제 자료 · OpenDART / KOSIS</option>
            <option value="snapshot">공식 저장 자료 · 확보 시점 기준</option>
          </select>
          <p id="data-mode-help" className="field-help">{dataMode === "snapshot"
            ? "미리 확보한 공식 자료를 사용합니다. 외부 자료를 새로 조회하지 않으며 확보 이후 개정·정정은 반영하지 않습니다. 저장 시점과 지원 범위를 확인하고 조건을 승인해 주세요."
            : dataMode === "live"
            ? "KOSIS는 15~29세 고용률의 시도별 연간 값(2020~2024년), OpenDART는 삼성전자 연간 연결 매출액(2022·2024년)을 지원합니다. 승인 후 자료를 확인하며, 같은 자료는 재사용 기한 안에서 다시 사용할 수 있습니다."
            : "실제 공공데이터를 조회하지 않는 실습 자료입니다."}</p>
        </div>
        <div className="interpretation-choice">
          <label htmlFor="interpretation-method">질문 해석 방식</label>
          <select id="interpretation-method" value={interpretationMethod} aria-describedby="interpretation-help"
            onChange={(event) => changeInterpretationMethod(event.target.value as InterpretationMethod)}>
            <option value="mock_rules">모의 규칙 · 외부 전송 없음</option>
            <option value="gemini">Gemini · 실제 모델</option>
          </select>
          <p id="interpretation-help" className="field-help">{dataMode === "snapshot"
            ? (interpretationMethod === "gemini"
              ? "‘질문 분석’을 누르면 질문을 Gemini로 보냅니다. 공식 저장 자료의 값과 계산은 조건 승인 후 확인합니다."
              : "질문을 외부로 보내지 않고 모의 규칙으로 해석합니다. 공식 저장 자료의 값과 계산은 조건 승인 후 확인합니다.")
            : dataMode === "live"
            ? (interpretationMethod === "gemini"
              ? "‘질문 분석’을 누르면 질문을 Gemini로 보냅니다. 공식 자료 조회와 계산은 조건 승인 후 별도로 실행합니다."
              : "질문을 외부로 보내지 않고 모의 규칙으로 해석합니다. 공식 자료 조회와 계산은 조건 승인 후 별도로 실행합니다.")
            : interpretationMethod === "gemini" ? "‘질문 분석’을 누르면 입력한 질문을 Google의 Gemini로 보냅니다. 조회 자료와 브리핑은 계속 모의 자료이며, 실제 취재 근거로 사용할 수 없습니다."
            : "질문을 외부로 보내지 않고 모의 규칙으로 해석합니다. 조회 자료와 브리핑도 모의 자료입니다."}</p>
        </div>
        <form onSubmit={submit}>
          <label htmlFor="question">질문 입력</label>
          <textarea id="question" value={question} onChange={(event) => changeQuestion(event.target.value)} rows={3} maxLength={1000} />
          <button className="primary" type="submit" disabled={busy !== null || question.trim().length < 3}>
            {busy === "plan" ? "조건을 해석하는 중…" : "질문 분석"}
          </button>
        </form>
      </section>

      <WorkshopGuide selected={guide} plan={plan} draft={draft} result={result} busy={busy} error={error}
        onStart={startGuide} onClose={() => setGuide(null)} onApply={applyGuideConditions} />
      {error && <p className="error request-error" role="alert">{error}</p>}
      {error && plan?.data_mode === "live" && draft && <section className="card">
        <p>실제 조회 결과를 표시하지 않았습니다. 미리 확보한 공식 저장 자료를 사용할 수도 있습니다. 저장 시점과 지원 조건을 확인하고 다시 승인해야 합니다.</p>
        <button type="button" onClick={prepareSnapshot} disabled={busy !== null}>저장 자료로 조건 다시 확인</button>
      </section>}
      {fallbackReason && <p className="notice">저장 자료로 전환하기 전 실제 조회 안내: {fallbackReason}</p>}
      {!plan || !draft ? (
        <section className="empty-state" role="status">
          <strong>{busy === "plan" ? "질문에서 조회 조건을 찾고 있습니다." : "먼저 질문을 분석해 주세요."}</strong>
          <p>자료원과 조건을 확인하고 ‘이 조건으로 조회’를 누르면 두 응답과 선택한 자료를 비교할 수 있습니다.</p>
        </section>
      ) : (
        <div className="result-grid">
          <section className="card conditions-card" aria-labelledby="conditions-title" aria-busy={busy === "execute"}>
            <p className="step">02 · 질문 해석과 조건 확인</p>
            <h2 id="conditions-title">{sourceLabel(plan.query_plan.selected_source)}</h2>
            {plan.conditions_preserved ? <p className="field-help">기존 입력 조건을 유지했습니다. 외부 질문 해석을 다시 하지 않았습니다.</p>
              : plan.interpretation_method === "mock_rules" && <p className="field-help">질문 해석: 모의 규칙 · Gemini를 호출하지 않았습니다.</p>}
            {plan.interpretation_method === "gemini" && <p className="field-help">질문 해석: Gemini ({plan.interpretation_model}) · {plan.data_mode === "snapshot" ? "공식 저장 자료는 조건 승인 후 사용합니다." : plan.data_mode === "live" ? "공식 자료는 조건 승인 후 조회합니다." : "자료 조회와 브리핑은 모의 자료입니다."}</p>}
            <p>{plan.query_plan.selection_reason}</p>
            {!result && plan.data_mode === "snapshot" && plan.snapshot && <SnapshotNotice snapshot={plan.snapshot} preview />}
            {draft.selected_source !== "undetermined" && plan.query_plan.clarification_questions.length > 0 && <details className="planning-notes">
              <summary>처음 질문을 해석할 때 확인이 필요했던 내용</summary>
              <ul>{plan.query_plan.clarification_questions.map((message, index) => <li key={index}>{message}</li>)}</ul>
              <p className="field-help">아래에서 조건을 수정할 수 있습니다. 현재 조회 가능 여부는 입력란 아래의 안내를 확인해 주세요.</p>
            </details>}
            <p className="condition-status" role="status">
              {modifiedFields.length > 0 ? "참가자가 조건을 수정했습니다." : plan.conditions_preserved ? "이전에 입력한 조건입니다." : "에이전트가 제시한 조건입니다."}
              {result ? (result.evidence.data_mode === "snapshot" ? " 승인한 조건으로 공식 저장 자료를 사용했습니다." : result.evidence.data_mode === "live" ? (result.cache ? ` ${cacheLabel(result.cache)}` : " 승인한 조건으로 실제 조회했습니다.") : " 승인한 조건으로 모의 조회했습니다.") : " 조건을 확인한 뒤 승인해 주세요."}
            </p>
            {draft.selected_source === "undetermined" ? (
              <div className="notice" role="status">
                <strong>질문을 조금 더 구체화해 주세요.</strong>
                <p>{errors[0]}</p>
                <p>위의 실습 질문 예시를 선택해 시작할 수도 있습니다.</p>
              </div>
            ) : (
              <form onSubmit={approve}>
                <div className="condition-fields">
                  {fields.map((field) => {
                    const label = conditionLabels[field] ?? field;
                    const value = conditionValue(draft, field);
                    const options = plan.field_options[field];
                    const modified = modifiedFields.includes(field);
                    const id = `condition-${field.replaceAll(".", "-")}`;
                    return (
                      <div className="condition-field" key={field}>
                        <label htmlFor={id}>{label}{modified && <span className="modified" aria-hidden="true">수정됨</span>}</label>
                        {field === "period" ? (
                          <input id={id} value={value} placeholder="예: 2020-2024" maxLength={20}
                            aria-describedby="period-help" onChange={(event) => changeCondition(field, event.target.value)} />
                        ) : (
                          <select id={id} value={value} onChange={(event) => changeCondition(field, event.target.value)}>
                            <option value="">선택해 주세요</option>
                            {options?.map((option) => <option key={option} value={option}>{option}</option>)}
                          </select>
                        )}
                        {modified && <small>처음 제시된 값: {original ? conditionValue(original, field) || "확인 필요" : "확인 필요"}</small>}
                      </div>
                    );
                  })}
                </div>
                <p id="period-help" className="field-help">
                  {plan.data_mode !== "mock" && draft.selected_source === "opendart"
                    ? "원문을 대조한 2022년과 2024년의 연간 연결 매출액만 지원합니다. 기간에 2022-2024를 입력해 주세요."
                    : plan.data_mode !== "mock" && draft.selected_source === "kosis"
                    ? "2020~2024년 안에서 서로 다른 시작·종료 연도의 연간 고용률을 비교합니다. 예: 2020-2024."
                    : plan.available_years?.length ? `가상 수치 자료는 ${plan.available_years[0]}~${plan.available_years[plan.available_years.length - 1]}년을 지원합니다. 서로 다른 시작·종료 연도의 연간 값만 비교합니다.`
                    : "시작 연도와 종료 연도의 연간 값을 비교합니다. 모의 실습은 1900~2100년 안의 서로 다른 두 연도를 입력받으며, 실제 자료의 제공 기간을 뜻하지 않습니다."}
                </p>
                {draft.selected_source === "kosis" && <p className="field-help synthetic-label">{plan.data_mode !== "mock"
                  ? `${plan.data_mode === "snapshot" ? "저장된" : "실제"} 자료는 15~29세 고용률만 지원하며, 15~34세·취업자 수로 바꾸어 조회하지 않습니다. ‘전국’은 17개 시도, ‘수도권’은 서울·인천·경기, ‘비수도권’은 나머지 14개 시도를 각각 비교합니다. 권역 전체 고용률을 평균내지 않습니다.`
                  : "공식 통계가 아닌 가상 숫자로 계산합니다. ‘전국’은 가상 지역 A~D, ‘수도권’은 A·B, ‘비수도권’은 C·D를 고르는 실습 분류입니다."}</p>}
                {errors.length > 0 ? (
                  <div className="notice" role="status">
                    <strong>조회 전에 확인해 주세요.</strong>
                    <ul>{errors.map((message) => <li key={message}>{message}</li>)}</ul>
                  </div>
                ) : (
                  <p className="field-help" role="status">{result ? "승인한 조회 조건과 두 응답을 아래에서 비교해 주세요." : "조건이 모두 입력됐습니다. 승인하면 일반 응답 예시와 근거 기반 브리핑이 함께 표시됩니다."}</p>
                )}
                <button className="primary" type="submit" disabled={busy !== null || errors.length > 0}>
                  {busy === "execute" ? (dataMode === "snapshot" ? "저장 자료로 계산하는 중…" : dataMode === "live" ? (draft.selected_source === "kosis" ? "통계 자료를 조회하는 중…" : "공시 자료를 조회하는 중…") : "모의 자료를 준비하는 중…") : "이 조건으로 조회"}
                </button>
                <p className="field-help">조건을 수정하면 결과와 검토 표시가 숨겨집니다. 바꾼 조건을 다시 승인하면 직전 결과와 비교할 수 있습니다. 질문을 바꾸거나 다시 분석하면 비교도 초기화됩니다.</p>
              </form>
            )}
          </section>

          {result && (
            <>
              {previousResult && <ConditionComparison previous={previousResult} current={result} />}
              <ReviewSession key={result.request_id} result={result}>
                <section className="card evidence-card" aria-labelledby="evidence-title">
                  <p className="step">04 · 자료와 계산 근거</p>
                  <h2 id="evidence-title">{result.evidence.source_name}</h2>
                  <p>{result.evidence.table_or_report}</p>
                  <h3>승인된 조회 조건</h3>
                  <dl className="approved-conditions">
                    {Object.entries(result.evidence.query_parameters).map(([field, value]) => (
                      <div key={field}><dt>{conditionLabels[field] ?? field}</dt><dd>{field === "selected_source" ? sourceLabel(result.query_plan.selected_source) : value}</dd></div>
                    ))}
                  </dl>
                  <dl>
                    <div><dt>단위</dt><dd>{result.calculation ? `입력 ${result.calculation.input_unit} · 결과 ${result.calculation.result_unit}` : result.financial_calculation ? `입력 원 · 결과 ${result.financial_calculation.result_unit}` : result.evidence.unit}</dd></div>
                    <div><dt>{result.evidence.data_mode === "snapshot" ? "저장 자료의 원래 조회 시각" : result.evidence.data_mode === "live" ? "자료 조회 완료 시각" : result.calculation ? "가상 자료 계산 시각" : "모의 자료 생성 시각"}</dt><dd>{new Date(result.evidence.retrieved_at).toLocaleString("ko-KR")}</dd></div>
                    <div><dt>계산식</dt><dd>{result.evidence.formula}</dd></div>
                  </dl>
                  <CacheNotice result={result} />
                  {result.evidence.data_mode === "snapshot" && result.snapshot && <SnapshotNotice snapshot={result.snapshot} />}
                  {result.financial_calculation && <FinancialEvidence result={result} />}
                  {result.calculation?.data_origin === "kosis" && <KosisEvidence result={result} />}
                  {result.calculation && <CalculationTable calculation={result.calculation} comparison={result.query_plan.comparison} />}
                  <h3>자료 이용 시 주의사항</h3>
                  <ul>{result.evidence.caveats.map((item) => <li key={item}>{item}</li>)}</ul>
                  <span className="data-mode">{result.evidence.data_mode === "snapshot" ? "공식 저장 자료 · 최신 조회 아님 · 사람 검토 필요" : result.evidence.data_mode === "live" ? (result.calculation?.data_origin === "kosis" ? "공식 통계 실제 조회 · 사람 검토 필요" : "공식 공시 실제 조회 · 사람 검토 필요") : result.calculation ? "가상 수치 계산 · 공식 통계 아님" : "모의 자료 · 실제 조회 전"}</span>
                </section>
              </ReviewSession>
            </>
          )}
        </div>
      )}
    </main>
  );
}

export default App;
