import { useEffect, useRef, useState, type FormEvent } from "react";
import { type ApiGet, type ApiPost } from "./api";
import { OperationsPanel } from "./OperationsPanel";
import { sourceLabel } from "./conditions";
import type { CitedText, ResearchConditions, ResearchPlan, ResearchResult } from "./researchTypes";

const examples = ["SK하이닉스 최근 실적이 좋아졌는지 숫자로 확인하고 싶어.", "수도권 청년 고용은 어떻게 달라졌을까?"];
const conditionLabels = { entity: "대상", metrics: "지표", start_year: "시작 연도", end_year: "종료 연도", comparison: "비교 기준" };

export function researchConditionKey(c: ResearchConditions): string {
  return JSON.stringify([c.selected_source, c.entity, c.company_code, [...c.metrics].sort(), c.start_year, c.end_year, c.comparison, c.statement_basis, c.age_range, c.frequency]);
}

function localErrors(plan: ResearchPlan, draft: ResearchConditions): string[] {
  const errors: string[] = [];
  if (plan.field_errors.scope) errors.push(plan.field_errors.scope);
  if (draft.selected_source === "undetermined") errors.push("기업 실적 또는 지역 청년 고용 중 조사할 내용을 알려 주세요.");
  if (draft.selected_source === "opendart" && !plan.companies.some(c => c.code === draft.company_code && c.name === draft.entity)) errors.push("회사를 확인한 뒤 조사 계획을 다시 요청해 주세요.");
  if (draft.selected_source === "kosis" && !plan.available_entities.includes(draft.entity)) errors.push("조회할 지역을 선택해 주세요.");
  if (!draft.metrics.length || draft.metrics.some(m => !plan.available_metrics.includes(m))) errors.push("조회할 지표를 선택해 주세요.");
  const { start_year: start, end_year: end } = draft;
  if (start === null || end === null || start >= end || end - start >= 5 || !Array.from({ length: Math.max(0, Math.min(6, (end ?? 0) - (start ?? 0) + 1)) }, (_, i) => (start ?? 0) + i).every(y => plan.available_years.includes(y))) errors.push("제공되는 기간 안에서 연속된 2~5개 연도를 선택해 주세요.");
  if (draft.frequency !== "연간" || draft.selected_source === "opendart" && draft.statement_basis !== "연결" || draft.selected_source === "kosis" && draft.age_range !== "15-29세") errors.push("지원하지 않는 주기·기준·연령입니다. 자연어 수정 요청으로 조사 범위를 확인해 주세요.");
  return errors;
}

export function ResearchWorkshop({ post, get }: { post: ApiPost; get: ApiGet }) {
  const [question, setQuestion] = useState(examples[0]);
  const [mode, setMode] = useState<"mock" | "live">("mock");
  const [method, setMethod] = useState<"mock_rules" | "gemini">("mock_rules");
  const [plan, setPlan] = useState<ResearchPlan | null>(null);
  const [draft, setDraft] = useState<ResearchConditions | null>(null);
  const [revisionText, setRevisionText] = useState("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [busy, setBusy] = useState<"plan" | "execute" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revised, setRevised] = useState(false);
  const version = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { version.current++; controller.current?.abort(); }, []);

  function invalidate(clearPlan = false) {
    version.current++;
    controller.current?.abort();
    setResult(null); setBusy(null); setError(null);
    if (clearPlan) { setPlan(null); setDraft(null); setRevisionText(""); setRevised(false); }
  }
  function changeQuestion(value: string) { invalidate(true); setQuestion(value); }
  function changeField<K extends keyof ResearchConditions>(key: K, value: ResearchConditions[K]) {
    if (!draft) return;
    invalidate(); setDraft({ ...draft, [key]: value });
  }
  async function planQuestion(event?: FormEvent, selected?: ResearchConditions) {
    event?.preventDefault();
    const previous = selected ?? draft;
    const previousPlan = plan;
    const refining = !!selected || !!revisionText.trim();
    const instruction = selected ? "선택한 회사로 조사 계획을 다시 확인해 주세요." : revisionText.trim();
    invalidate(); setPlan(null); setDraft(null);
    const current = version.current;
    const abort = new AbortController(); controller.current = abort; setBusy("plan");
    try {
      const response = await post<ResearchPlan>("/api/v1/research/plan", {
        question: question.trim(), mode, interpretation_method: method,
        ...(refining && previous ? { previous_conditions: previous, revision: instruction } : {}),
      }, abort.signal);
      if (current !== version.current) return;
      if (response.data_mode !== mode || response.question !== question.trim()) throw new Error("질문이나 자료 모드가 응답과 맞지 않습니다. 다시 계획을 요청해 주세요.");
      setPlan(response); setDraft(response.conditions); setRevisionText(""); setRevised(refining);
    } catch (caught) {
      if (current === version.current) {
        setError(caught instanceof Error ? caught.message : "조사 계획을 확인하지 못했습니다.");
        // Preserve the previous draft for another explicit refinement attempt.
        setDraft(previous);
        if (refining) setPlan(previousPlan);
      }
    } finally { if (current === version.current) setBusy(null); }
  }
  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!plan || !draft || localErrors(plan, draft).length || revisionText.trim()) return;
    invalidate();
    const current = version.current;
    const abort = new AbortController(); controller.current = abort; setBusy("execute");
    try {
      const response = await post<ResearchResult>("/api/v1/research/execute", {
        question: question.trim(), mode, approved: true, conditions: draft,
        briefing_method: method === "gemini" ? "gemini" : "scripted",
      }, abort.signal);
      if (current !== version.current) return;
      if (response.data_mode !== mode || response.question !== question.trim() || researchConditionKey(response.conditions) !== researchConditionKey(draft)) throw new Error("승인한 조건과 결과가 맞지 않습니다. 다시 확인해 주세요.");
      setResult(response);
    } catch (caught) { if (current === version.current) setError(caught instanceof Error ? caught.message : "자료를 조회하지 못했습니다."); }
    finally { if (current === version.current) setBusy(null); }
  }

  const errors = plan && draft ? localErrors(plan, draft) : [];
  function modified(key: keyof ResearchConditions) {
    return draft && plan && JSON.stringify(draft[key]) !== JSON.stringify(plan.conditions[key]);
  }
  return <main className="shell">
    <header className="topbar"><div><p className="eyebrow">NewsTech Initiatives 2026 · 2부 실습</p><h1>질문에서 근거 기반 브리핑까지</h1></div><span className="mode">{mode === "mock" ? "모의 자료 모드" : "공식 실제 자료"}</span></header>
    <OperationsPanel get={get} />
    <section className="question-panel" aria-labelledby="research-question-title">
      <div className="section-heading"><span>01</span><div><h2 id="research-question-title">자유롭게 취재 질문하기</h2><p>조사할 내용을 말하면 자료원과 계획을 제안합니다. 승인 후 자료와 브리핑을 확인합니다.</p></div></div>
      <p className="field-help">기업 한 곳의 연간 연결 매출액·영업이익, 또는 지역 청년 고용률을 조사할 수 있습니다. 회사 간 비교·분기 실적·다른 통계 주제는 아직 지원하지 않습니다.</p>
      <div className="sample-list" aria-label="2부 질문 예시">{examples.map(example => <button key={example} onClick={() => changeQuestion(example)}>{example}</button>)}</div>
      <div className="research-choices">
        <label>조회 자료<select value={mode} onChange={e => { invalidate(true); setMode(e.target.value as typeof mode); if (e.target.value === "live") setMethod("gemini"); }}><option value="mock">모의 자료 · 외부 조회 없음</option><option value="live">공식 실제 자료 · OpenDART / KOSIS</option></select></label>
        <label>계획·브리핑 작성 방식<select value={method} onChange={e => { invalidate(true); setMethod(e.target.value as typeof method); }}><option value="mock_rules">모의 규칙·문장 · 연습용</option><option value="gemini">Gemini · 실제 모델</option></select></label>
      </div>
      <p className="field-help">{method === "gemini" ? "질문과 수정 요청을 Gemini로 보냅니다. 승인 후에는 조회 근거와 계산 결과를 보내 브리핑을 작성합니다." : "모의 규칙은 예시 질문 중심의 연습용입니다. 자유로운 표현의 질문 해석과 AI 브리핑은 Gemini 방식에서 경험할 수 있습니다."} {mode === "live" ? "계획 단계에는 회사·보고서 목록만 확인합니다. 숫자는 승인 후 조회합니다." : "가상 자료는 실제 취재 근거로 사용할 수 없습니다."}</p>
      <form onSubmit={e => void planQuestion(e)}><label htmlFor="research-question">취재 질문 입력</label><textarea id="research-question" rows={3} maxLength={1000} value={question} onChange={e => changeQuestion(e.target.value)} /><button className="primary" disabled={busy !== null || question.trim().length < 3}>{busy === "plan" ? "조사 계획을 준비하는 중…" : "조사 계획 제안받기"}</button></form>
    </section>
    {error && <p role="alert" className="error request-error">{error}</p>}
    {plan && draft && <section className="card research-plan" aria-labelledby="research-plan-title">
      <div className="section-heading"><span>02</span><div><h2 id="research-plan-title">에이전트가 제안한 조사 계획</h2><p>{sourceLabel(draft.selected_source)} · {plan.selection_reason}</p></div></div>
      <p className="field-help">{plan.interpretation_method === "gemini" ? `Gemini 질문 해석 · ${plan.interpretation_model}` : "모의 규칙으로 구성한 계획"}</p>
      <p className="notice">{plan.metadata_notice}</p>
      {!!plan.proposals.length && <div><h3>승인 전에 확인할 제안</h3><ul>{plan.proposals.map(p => <li key={p}>{p}</li>)}</ul></div>}
      {!!plan.clarification_questions.length && <details open><summary>처음 계획에서 확인할 내용</summary><ul>{plan.clarification_questions.map(q => <li key={q}>{q}</li>)}</ul><p className="field-help">아래에서 조건을 고치거나 수정 요청을 보내 주세요. 현재 조건의 확인 결과는 조회 버튼 위에 표시합니다.</p></details>}
      {revised && <p className="modified-badge" role="status">수정 요청을 반영한 계획입니다. 다시 확인하고 승인해 주세요.</p>}
      {plan.companies.length > 1 && <div className="sample-list" aria-label="회사 후보">{plan.companies.map(company => <button key={company.code} disabled={busy !== null} onClick={() => void planQuestion(undefined, { ...draft, entity: company.name, company_code: company.code })}>{company.name} ({company.stock_code}) · 이 회사로 계획 확인</button>)}</div>}
      <form onSubmit={execute}>
        <div className="condition-fields">
          <div className="condition-field"><label htmlFor="research-entity">대상 {modified("entity") && <span className="modified-badge">수정됨</span>}</label>{draft.selected_source === "kosis" ? <select id="research-entity" value={draft.entity} onChange={e => changeField("entity", e.target.value)}><option value="">지역 선택</option>{plan.available_entities.map(v => <option key={v}>{v}</option>)}</select> : <input id="research-entity" readOnly value={draft.entity} aria-describedby="company-help" />}<p className="field-help" id="company-help">{draft.selected_source === "opendart" ? "회사를 바꾸려면 아래 수정 요청에 회사명을 적어 주세요." : "시도 비교와 개별 시도 조회를 선택할 수 있습니다."}</p></div>
          <fieldset className="condition-field"><legend>지표 {modified("metrics") && <span className="modified-badge">수정됨</span>}</legend>{plan.available_metrics.map(metric => <label className="research-metric" key={metric}><input type="checkbox" checked={draft.metrics.includes(metric)} onChange={e => changeField("metrics", e.target.checked ? [...draft.metrics, metric] : draft.metrics.filter(m => m !== metric))} />{metric}</label>)}</fieldset>
          {(["start_year", "end_year"] as const).map(key => <div className="condition-field" key={key}><label htmlFor={`research-${key}`}>{conditionLabels[key]} {modified(key) && <span className="modified-badge">수정됨</span>}</label><select id={`research-${key}`} value={draft[key] ?? ""} onChange={e => changeField(key, e.target.value ? Number(e.target.value) : null)}><option value="">연도 선택</option>{plan.available_years.map(y => <option key={y} value={y}>{y}년</option>)}</select></div>)}
          <div className="condition-field"><label htmlFor="research-comparison">비교 기준 {modified("comparison") && <span className="modified-badge">수정됨</span>}</label><select id="research-comparison" value={draft.comparison} onChange={e => changeField("comparison", e.target.value)}><option>증감 폭</option><option>증감률</option></select></div>
        </div>
        <p>{draft.frequency} · {draft.selected_source === "opendart" ? `${draft.statement_basis} 재무제표` : `연령 ${draft.age_range}`}</p>
        {!!errors.length && <div className="clarification" role="status"><strong>조회 전에 확인해 주세요.</strong><ul>{errors.map(e => <li key={e}>{e}</li>)}</ul></div>}
        {revisionText.trim() && <p className="notice">작성 중인 수정 요청을 먼저 계획에 반영해 주세요.</p>}
        <button className="primary" disabled={busy !== null || errors.length > 0 || !!revisionText.trim()}>{busy === "execute" ? "자료 조회·계산·브리핑 작성 중…" : "이 조건으로 조회"}</button>
        <p className="field-help">승인한 뒤에만 자료와 브리핑을 표시합니다. 질문·조건 변경과 다시 조회는 검토 상태를 초기화합니다.</p>
      </form>
      <form className="research-refinement" onSubmit={e => void planQuestion(e)}><label htmlFor="research-revision">계획을 말로 수정하기</label><textarea id="research-revision" rows={2} maxLength={1000} placeholder="예: 삼성전자로 바꾸고, 최근 2년의 매출만 봐줘." value={revisionText} onChange={e => { invalidate(); setRevisionText(e.target.value); }} /><button disabled={busy !== null || !revisionText.trim()}>수정 요청 반영</button></form>
    </section>}
    {result && <ResearchResultView key={result.request_id} result={result} />}
  </main>;
}

function Citation({ value }: { value: CitedText }) {
  return <>{value.text} <span className="fact-citations">{value.evidence_ids.map(id => <a key={id} href={`#research-${id}`} aria-label={`${id} 근거 보기`}>[{id}]</a>)}</span></>;
}

function ResearchResultView({ result }: { result: ResearchResult }) {
  const [checked, setChecked] = useState<string[]>([]);
  const c = result.conditions;
  const { content } = result.brief;
  const conditions = [["대상", c.entity], ["지표", c.metrics.join(" · ")], ["기간", `${c.start_year}~${c.end_year}년`], ["비교 기준", c.comparison], ["주기", c.frequency], [c.selected_source === "opendart" ? "재무제표 기준" : "연령", c.selected_source === "opendart" ? c.statement_basis : c.age_range]];
  return <div className="research-results">
    <section className="card" aria-labelledby="research-brief-title"><p className="step">03 · 근거 기반 브리핑</p><h2 id="research-brief-title">취재 브리핑 초안</h2>
      <span className="data-mode">{result.data_mode === "mock" ? "가상 자료 · 실제 취재 근거로 사용 불가" : "공식 자료 · 사람 검토 필요"}</span>
      <p className="field-help">{result.brief.generation_method === "gemini" ? `Gemini 작성 · ${result.brief.model}` : "모의 문장 작성 · 실제 모델 호출 없음"}</p>
      {result.brief.status === "failed" && <p className="error" role="alert">{result.brief.error}</p>}
      {content && <><p className="response-summary"><Citation value={content.summary} /></p><h3>근거에서 관찰한 내용</h3><ul>{content.findings.map((f, i) => <li key={i}><Citation value={f} /></li>)}</ul><h3>이 자료만으로 단정하기 어려운 부분</h3><ul>{content.limitations.map((v, i) => <li key={i}>{v}</li>)}</ul><h3>후속 취재 질문</h3><ul>{content.follow_up_questions.map((v, i) => <li key={i}>{v}</li>)}</ul></>}
      <p className="notice">숫자와 근거 참조를 확인한 초안입니다. 문장의 의미·인과관계가 검증됐다는 뜻은 아닙니다.</p>
    </section>
    <section className="card evidence-card" aria-labelledby="research-evidence-title"><p className="step">04 · 자료와 계산 근거</p><h2 id="research-evidence-title">{result.source_name}</h2><p>{result.table_or_report}</p><h3>승인된 조회 조건</h3><dl className="approved-conditions">{conditions.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {result.cache && <p className="notice">{result.cache.status === "miss" ? "새로 조회한 자료" : "기존 조회 자료 재사용"} · 원래 보관 시각 {new Date(result.cache.stored_at).toLocaleString("ko-KR")} · 재사용 기한 {new Date(result.cache.expires_at).toLocaleString("ko-KR")}</p>}
      <div className="research-table-wrap"><table><caption>{result.data_mode === "mock" ? "가상 원자료와 코드 계산" : "조회한 원자료와 코드 계산"} · 브리핑의 근거 번호로 찾아보세요.</caption><thead><tr><th>근거</th><th>대상·지표</th><th>기간</th><th>값·단위</th><th>계산·출처·시각</th></tr></thead><tbody>{result.facts.map(f => <tr key={f.id} id={`research-${f.id}`} tabIndex={-1}><th scope="row">{f.id}</th><td>{f.entity}<br />{f.metric}{f.rank != null && <span className="field-help"> · 변화값 {f.rank}위</span>}</td><td>{f.period}</td><td className="numeric">{/^-?[0-9]+$/.test(f.value) ? BigInt(f.value).toLocaleString("ko-KR") : f.value} {f.unit}</td><td>{f.formula}<br />{f.source_urls.map((url, i) => /^https:\/\/(dart\.fss\.or\.kr|kosis\.kr)\//.test(url) ? <a key={url} href={url} target="_blank" rel="noreferrer">공식 원문 {i + 1} </a> : null)}<br />{result.data_mode === "mock" ? "가상 자료 생성" : "자료 조회"}: {new Date(f.retrieved_at).toLocaleString("ko-KR")}<details><summary>조회·계산 상세</summary><dl>{Object.entries(f.details).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details></td></tr>)}</tbody></table></div>
      <h3>자료 이용 시 주의사항</h3><ul>{result.caveats.map(v => <li key={v}>{v}</li>)}</ul>
    </section>
    <section className="card human-review" aria-labelledby="research-review-title"><p className="step">05 · 사람의 검토</p><h2 id="research-review-title">이 결과의 실습 검토</h2><p className="review-progress" role="status">{checked.length === 4 ? "실습 검토 항목 확인 완료" : checked.length ? "실습 검토 중" : "실습 검토 전"} · {checked.length}/4개 확인</p><fieldset className="review-checklist"><legend>직접 확인한 항목</legend>{["승인된 조회 조건", "자료의 출처와 시각", "원자료·계산과 브리핑 인용", "해석의 한계와 후속 취재"].map(item => <label className="review-item" key={item}><input type="checkbox" checked={checked.includes(item)} onChange={e => setChecked(e.target.checked ? [...checked, item] : checked.filter(v => v !== item))} /><span>{item}</span></label>)}</fieldset><p className="notice">실습 항목 확인 표시이며, 사실 검증 완료나 기사 사용 승인이 아닙니다. {result.data_mode === "mock" && "가상 자료는 실제 취재 근거로 사용할 수 없습니다."}</p><p className="field-help">질문·조건 변경, 다시 조회, 1부/2부 전환, 새로고침 시 검토 표시가 초기화됩니다.</p></section>
  </div>;
}
