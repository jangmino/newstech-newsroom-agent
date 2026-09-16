import { FormEvent, useEffect, useRef, useState } from "react";
import {
  conditionErrors, conditionLabels, conditionValue, editableConditions, sourceLabel, updateCondition,
} from "./conditions";
import { ResponseComparison } from "./ResponseComparison";
import type {
  ApiErrorDetail, ExecuteRequest, ExecutionResponse, PlanRequest, PlanResponse, QueryConditions,
} from "./types";

const samples = [
  "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?",
  "삼성전자의 최근 실적은 악화됐는가?",
];

async function post<T>(path: string, body: PlanRequest | ExecuteRequest, signal: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal,
    });
  } catch {
    throw new Error("요청을 보내지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: ApiErrorDetail } | null;
    const detail = payload?.detail;
    if (detail?.message && detail.field_errors) {
      throw new Error([detail.message, ...Object.values(detail.field_errors)].join(" "));
    }
    throw new Error("요청을 처리하지 못했습니다. 입력한 내용은 유지됩니다. 다시 시도해 주세요.");
  }
  try {
    return await response.json() as T;
  } catch {
    throw new Error("응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.");
  }
}

function App() {
  const [question, setQuestion] = useState(samples[0]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [draft, setDraft] = useState<QueryConditions | null>(null);
  const [result, setResult] = useState<ExecutionResponse | null>(null);
  const [busy, setBusy] = useState<"plan" | "execute" | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    setBusy(null);
    setError(null);
  }

  function changeQuestion(value: string) {
    invalidate();
    setQuestion(value);
    setPlan(null);
    setDraft(null);
  }

  function changeCondition(field: string, value: string) {
    if (!draft) return;
    invalidate();
    setDraft(updateCondition(draft, field, value));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    invalidate();
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
        question: question.trim(), mode: "mock",
      }, request.signal);
      if (current !== revision.current) return;
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
      const response = await post<ExecutionResponse>("/api/v1/execute", {
        question: plan.question, mode: "mock", approved: true, conditions,
      }, request.signal);
      if (current !== revision.current) return;
      if (!response.general_response?.text || response.general_response.data_mode !== "mock"
        || response.general_response.generation_method !== "scripted") {
        throw new Error("응답 비교를 준비하지 못했습니다. 잠시 후 다시 조회해 주세요.");
      }
      setDraft(conditions);
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
        <span className="mode">모의 자료 모드</span>
      </header>

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
        <form onSubmit={submit}>
          <label htmlFor="question">질문 입력</label>
          <textarea id="question" value={question} onChange={(event) => changeQuestion(event.target.value)} rows={3} maxLength={1000} />
          <button className="primary" type="submit" disabled={busy !== null || question.trim().length < 3}>
            {busy === "plan" ? "조건을 해석하는 중…" : "질문 분석"}
          </button>
        </form>
      </section>

      {error && <p className="error request-error" role="alert">{error}</p>}
      {!plan || !draft ? (
        <section className="empty-state" role="status">
          <strong>{busy === "plan" ? "질문에서 조회 조건을 찾고 있습니다." : "먼저 질문을 분석해 주세요."}</strong>
          <p>자료원과 조건을 확인하고 ‘이 조건으로 조회’를 누르면 두 응답과 모의 자료를 비교할 수 있습니다.</p>
        </section>
      ) : (
        <div className="result-grid">
          <section className="card conditions-card" aria-labelledby="conditions-title" aria-busy={busy === "execute"}>
            <p className="step">02 · 질문 해석과 조건 확인</p>
            <h2 id="conditions-title">{sourceLabel(plan.query_plan.selected_source)}</h2>
            <p>{plan.query_plan.selection_reason}</p>
            <p className="condition-status" role="status">
              {modifiedFields.length > 0 ? "참가자가 조건을 수정했습니다." : "에이전트가 제시한 조건입니다."}
              {result ? " 승인한 조건으로 모의 조회했습니다." : " 조건을 확인한 뒤 승인해 주세요."}
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
                <p id="period-help" className="field-help">시작 연도와 종료 연도의 연간 값을 비교합니다. 모의 실습은 1900~2100년 안의 서로 다른 두 연도를 입력받으며, 실제 자료의 제공 기간을 뜻하지 않습니다.</p>
                {errors.length > 0 ? (
                  <div className="notice" role="status">
                    <strong>조회 전에 확인해 주세요.</strong>
                    <ul>{errors.map((message) => <li key={message}>{message}</li>)}</ul>
                  </div>
                ) : (
                  <p className="field-help" role="status">{result ? "승인한 조회 조건과 두 응답을 아래에서 비교해 주세요." : "조건이 모두 입력됐습니다. 승인하면 일반 응답 예시와 근거 기반 브리핑이 함께 표시됩니다."}</p>
                )}
                <button className="primary" type="submit" disabled={busy !== null || errors.length > 0}>
                  {busy === "execute" ? "모의 자료를 준비하는 중…" : "이 조건으로 조회"}
                </button>
                <p className="field-help">조건을 수정하면 이전 승인과 결과가 해제됩니다. 조건 승인 후에도 결과는 사람의 검토가 필요합니다.</p>
              </form>
            )}
          </section>

          {result && (
            <>
              <ResponseComparison result={result} />
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
                  <div><dt>단위</dt><dd>{result.evidence.unit}</dd></div>
                  <div><dt>모의 자료 생성 시각</dt><dd>{new Date(result.evidence.retrieved_at).toLocaleString("ko-KR")}</dd></div>
                  <div><dt>계산식</dt><dd>{result.evidence.formula}</dd></div>
                </dl>
                <h3>자료 이용 시 주의사항</h3>
                <ul>{result.evidence.caveats.map((item) => <li key={item}>{item}</li>)}</ul>
                <span className="data-mode">모의 자료 · 실제 조회 전</span>
              </section>
            </>
          )}
        </div>
      )}
    </main>
  );
}

export default App;
