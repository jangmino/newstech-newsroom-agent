import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { ApiGet, ApiPost, EventProgress } from './api';
import { OperationsPanel } from './OperationsPanel';
import type { EventCatalog, EventConditions, EventDialogueTurn, EventExecuteRequest, EventPlan, EventResult, GeneralResponse } from './eventTypes';
import { Conditions, EventResults, labels, toolLabels, Trace } from './EventResults';
import { DialogueHistory, EventDialogue } from './EventDialogue';

const examples = [
  'NAVER와 카카오의 최근 한 달 투자·지분·소송 공시를 비교해 줘.',
  '서울의 청년 고용률은 최근 5년간 전국 집계와 비교해 어떻게 달라졌을까?',
  '최근 5년간 청년 고용률이 가장 많이 개선된 시도는 어디일까?',
  '현대자동차의 최근 실적은 악화됐는가?',
];
export function eventConditionKey(c: EventConditions) { return JSON.stringify(Object.keys(c).sort().map(k => [k, c[k as keyof EventConditions]])); }

export function EventWorkshop({ post, get, part }: { post: ApiPost; get: ApiGet; part: 1 | 2 }) {
  const [question, setQuestion] = useState(part === 1 ? examples[1] : '');
  const [catalog, setCatalog] = useState<EventCatalog | null>(null);
  const [mode, setMode] = useState<'live' | 'snapshot'>('live');
  const [snapshot, setSnapshot] = useState('');
  const [plan, setPlan] = useState<EventPlan | null>(null);
  const [draft, setDraft] = useState<EventConditions | null>(null);
  const [revision, setRevision] = useState('');
  const [conversation, setConversation] = useState<EventDialogueTurn[]>([]);
  const [result, setResult] = useState<EventResult | null>(null);
  const [previous, setPrevious] = useState<EventResult | null>(null);
  const [general, setGeneral] = useState<GeneralResponse | null>(null);
  const [busy, setBusy] = useState<'plan' | 'execute' | 'general' | null>(null);
  const [progress, setProgress] = useState<EventProgress | null>(null);
  const [error, setError] = useState('');
  const [generalError, setGeneralError] = useState('');
  const version = useRef(0); const abort = useRef<AbortController | null>(null); const last = useRef<EventResult | null>(null);
  const planHeading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { if (plan) planHeading.current?.focus(); }, [plan]);
  useEffect(() => { const controller = new AbortController(); void get<EventCatalog>('/api/v1/event/catalog', controller.signal).then(setCatalog).catch(() => { if (!controller.signal.aborted) setError('저장 자료 목록을 확인하지 못했습니다. 새로고침하거나 실제 조회를 진행해 주세요.'); }); return () => { controller.abort(); abort.current?.abort(); version.current++; }; }, [get]);
  function invalidate(clear = false) { version.current++; abort.current?.abort(); setResult(null); setGeneral(null); setPrevious(null); setBusy(null); setProgress(null); setError(''); setGeneralError(''); if (clear) { last.current = null; setPlan(null); setDraft(null); setRevision(''); setConversation([]); } }
  function changeQuestion(value: string) { invalidate(true); setQuestion(value); }
  function change<K extends keyof EventConditions>(field: K, value: EventConditions[K]) { if (!draft) return; invalidate(); setDraft({ ...draft, [field]: value }); }
  function chooseSnapshot(id: string) {
    invalidate(true); setSnapshot(id);
    const item = catalog?.snapshots.find(s => s.id === id); if (!item) return;
    setQuestion(item.question); setDraft(item.conditions);
    setPlan({ request_id: `snapshot-${id}`, question: item.question, conditions: item.conditions, model: null, proposals: ['공식 자료와 실제 모델 응답을 보관한 사례입니다. 최신 조회가 아니며 아래 고정 조건을 다시 승인해야 합니다.'], field_errors: {}, companies: [], trace: [], snapshot_id: id, status: 'ready', clarification: null });
  }
  async function propose(refinement = '') {
    if (busy || question.trim().length < 3 || (refinement.trim() && conversation.length >= 8)) return;
    refinement = refinement.trim();
    const previousDraft = draft; const previousPlan = plan;
    const nextConversation = refinement ? [...conversation, { question: plan?.clarification?.question ?? '계획에서 무엇을 바꿀까요?', answer: refinement }] : [];
    invalidate(); setRevision(refinement);
    const current = version.current; const controller = new AbortController(); abort.current = controller; setBusy('plan');
    try {
      const response = await post<EventPlan>('/api/v1/event/plan', { question: question.trim(), conversation: nextConversation, ...(refinement && previousDraft ? { previous_conditions: previousDraft, revision: refinement } : {}) }, controller.signal, value => { if (current === version.current) setProgress(value); });
      if (current !== version.current) return;
      if (response.question !== question.trim()) throw new Error('입력한 질문과 계획이 맞지 않습니다. 다시 요청해 주세요.');
      setPlan(response); setDraft(response.conditions); setRevision(''); setConversation(nextConversation);
    } catch (caught) { if (current === version.current) { setError(caught instanceof Error ? caught.message : '계획을 확인하지 못했습니다.'); if (refinement) { setDraft(previousDraft); setPlan(previousPlan); } } }
    finally { if (current === version.current) setBusy(null); }
  }
  function body(): EventExecuteRequest { return { question: question.trim(), conditions: draft!, approved: true, mode, ...(mode === 'snapshot' ? { snapshot_id: snapshot } : {}) }; }
  async function execute(e: FormEvent) {
    e.preventDefault(); if (busy || !draft || !plan || revision.trim() || needsDialogue) return;
    const request = body(); invalidate(); const current = version.current; const controller = new AbortController(); abort.current = controller; setBusy('execute');
    try {
      const response = await post<EventResult>('/api/v1/event/execute', request, controller.signal, value => { if (current === version.current) setProgress(value); });
      if (current !== version.current) return;
      if (response.question !== request.question || response.data_mode !== mode || eventConditionKey(response.conditions) !== eventConditionKey(request.conditions)) throw new Error('승인한 조건과 결과가 다릅니다. 계획을 다시 확인해 주세요.');
      setPrevious(last.current); last.current = response; setResult(response);
    } catch (caught) { if (current === version.current) setError(caught instanceof Error ? caught.message : '자료를 확인하지 못했습니다.'); }
    finally { if (current === version.current) setBusy(null); }
  }
  async function compare() {
    if (!result || !draft) return;
    const current = version.current; const controller = new AbortController(); abort.current = controller; setProgress(null); setBusy('general'); setGeneralError('');
    try {
      const response = await post<GeneralResponse>('/api/v1/event/general', body(), controller.signal, value => { if (current === version.current) setProgress(value); });
      if (current !== version.current) return;
      if (response.question !== result.question || eventConditionKey(response.conditions) !== eventConditionKey(result.conditions)) throw new Error('비교 응답의 조건이 다릅니다. 다시 요청해 주세요.');
      setGeneral(response);
    } catch (caught) { if (current === version.current) setGeneralError(caught instanceof Error ? caught.message : '일반 응답을 받지 못했습니다. 근거 결과는 유지됩니다.'); }
    finally { if (current === version.current) setBusy(null); }
  }
  function field(key: keyof EventConditions, options?: string[]) {
    if (!draft) return null;
    const value = String(draft[key]); const modified = plan && JSON.stringify(draft[key]) !== JSON.stringify(plan.conditions[key]);
    return <label className="condition-field" key={key}>{labels[key]} {modified && <span className="modified-badge">수정됨</span>}{options ? <select value={value} onChange={e => change(key, e.target.value)}>{!options.includes(value) && <option>{value}</option>}{options.map(v => <option key={v}>{v}</option>)}</select> : <input value={value} maxLength={10} placeholder={draft.tool === 'disclosures' ? 'YYYY-MM-DD' : draft.frequency === '분기' ? 'YYYY-Q1' : draft.frequency === '월간' ? 'YYYY-MM' : 'YYYY'} onChange={e => change(key, e.target.value)} />}</label>;
  }
  const needsDialogue = !!plan && (plan.status !== 'ready' || draft?.tool === 'undetermined' || !!plan.field_errors.scope);
  const clarification = plan?.clarification ?? { question: Object.values(plan?.field_errors ?? {}).join(' ') || '어떤 내용을 조사할지 조금 더 알려 주세요.', choices: [] };
  const metrics = draft?.tool === 'financials' ? ['매출액', '영업이익', '당기순이익'] : draft?.tool === 'disclosures' ? ['투자', '지분', '소송'] : draft?.tool === 'employment' ? ['고용률', '취업자 수', '실업률'] : [];
  return <main className="shell"><header className="topbar"><div><p className="eyebrow">NewsTech Initiatives 2026 · {part}부 실습</p><h1>{part === 1 ? '조건과 근거를 확인하는 취재 실습' : '질문에서 근거 기반 브리핑까지'}</h1></div><span className="mode">{mode === 'live' ? '공식 실제 자료' : '공식 저장 자료'}</span></header>
    <OperationsPanel get={get} event />
    <section className="question-panel"><div className="section-heading"><span>01</span><div><h2>취재 질문하기</h2><p>{part === 1 ? '진행자와 같은 예제로 조건 승인·근거 확인·사람 검토를 익힙니다.' : '궁금한 내용을 적어 주세요. 필요한 내용을 묻고 답하며 조사 가능한 질문으로 다듬습니다.'}</p></div></div>
      <p className="field-help">1부는 예제를 함께 따라가고, 2부는 내 질문으로 조사합니다. 두 실습 모두 같은 자료 조회·AI 브리핑·사람 검토 도구를 사용합니다.</p>
      <p className="field-help">기업 공시의 투자·지분·소송, 기업 재무 실적, 청년 고용을 공식 자료의 제공 범위에서 조사합니다.</p>
      <label>조회 자료<select value={mode} onChange={e => { invalidate(true); setMode(e.target.value as typeof mode); setSnapshot(''); }}><option value="live">공식 실제 자료 · Gemini 해석·브리핑</option><option value="snapshot">공식 저장 자료 · 장애 시 동일 조건 재생</option></select></label>
      {mode === 'snapshot' ? <><label>공식 저장 사례<select value={snapshot} onChange={e => chooseSnapshot(e.target.value)}><option value="">자료 선택</option>{catalog?.snapshots.map(s => <option value={s.id} key={s.id}>{s.title}</option>)}</select></label><p className="notice">자동으로 저장 자료로 바뀌지 않습니다. 선택한 사례의 질문·조건·원래 조회 시각을 확인하고 승인해 주세요.</p></> : <>
        <div className="sample-list" aria-label="행사 질문 예시">{examples.map(q => <button key={q} onClick={() => changeQuestion(q)}>{q}</button>)}</div>
        <form onSubmit={e => { e.preventDefault(); void propose(); }}><label>취재 질문 입력<textarea rows={3} maxLength={1000} value={question} placeholder="예: 삼성전자의 최근 재무 이슈가 궁금해요." onChange={e => changeQuestion(e.target.value)} /></label><button className="primary" disabled={!!busy || question.trim().length < 3}>{busy === 'plan' ? '계획을 준비하는 중…' : '조사 계획 제안받기'}</button></form>
        {conversation.length > 0 && <p className="field-help">아래 질답·수정 입력에서 이어가세요. 위 버튼을 다시 누르면 원 질문부터 계획을 새로 검토합니다.</p>}
        <p className="field-help">질문을 Gemini에 보냅니다. 승인 전에는 회사 목록과 제공 범위만 확인하며 자료 값과 브리핑은 조회하지 않습니다.</p>
        {part === 1 && <details><summary>조건을 바꾸고 확인할 장면</summary><p>고용률을 취업자 수로, 증감 폭을 증감률로 바꿔 보세요. 청년의 연령과 전국 집계·시도 순위의 차이도 확인합니다.</p><button onClick={() => changeQuestion('서울의 15-34세 청년 월간 고용률을 확인해 줘.')}>제공되지 않는 조합 질문하기</button><p>실제 공식 자료에 없는 조합을 확인하는 실습입니다. 공급자 장애를 꾸민 응답이 아닙니다.</p></details>}
      </>}
    </section>
    {busy && <section className="notice" role="status" aria-live="polite"><strong>{progress?.stage === 'waiting' ? '요청 순서를 기다리고 있습니다.' : progress?.stage === 'retry_wait' ? '공급자 안내에 따라 잠시 기다린 뒤 한 번 더 요청합니다.' : progress?.stage === 'source_wait' ? '승인한 공식 자료를 조회하거나 같은 자료의 조회 완료를 기다리고 있습니다.' : busy === 'plan' ? '질문을 해석하고 조사 계획을 준비하고 있습니다.' : busy === 'general' ? '일반 모델 응답을 작성하고 있습니다.' : '공식 자료 조회·계산·브리핑을 진행하고 있습니다.'}</strong><p>{progress?.provider && `${{ gemini: 'Gemini', opendart: 'OpenDART', kosis: 'KOSIS' }[progress.provider]} · `}접수 후 {Math.floor(progress?.elapsed_seconds ?? 0)}초 · 대기 {Math.floor(progress?.waited_seconds ?? 0)}초</p><p>순서가 되면 자동으로 진행합니다. 다시 누르지 않아도 됩니다. 대기는 최대 120초, 전체 처리는 최대 180초입니다.</p><button type="button" onClick={() => { version.current++; abort.current?.abort(); setBusy(null); setProgress(null); setError('요청을 취소했습니다. 이미 전송된 외부 호출은 끝날 수 있지만 후속 결과는 표시하지 않습니다. 입력한 조건은 유지됩니다.'); }}>요청 취소</button></section>}
    {error && <p role="alert" className="error request-error">{error}</p>}
    {plan && draft && <section className="card research-plan"><div className="section-heading"><span>{needsDialogue ? '질답' : '02'}</span><div><h2 tabIndex={-1} ref={planHeading}>{needsDialogue ? '조사 방향을 함께 정해 주세요' : '제안한 조회 조건을 검토해 주세요'}</h2><p>{needsDialogue ? (plan.status === 'unsupported' ? '지원 범위 확인' : '추가 확인 필요') : toolLabels[draft.tool]} · {plan.model ?? '공식 저장 사례'}</p></div></div>
      <DialogueHistory turns={conversation} />
      {needsDialogue ? <EventDialogue clarification={clarification} explanations={plan.proposals} unsupported={plan.status === 'unsupported' || !!plan.field_errors.scope} answer={revision} busy={!!busy} limitReached={conversation.length >= 8} onChange={value => { invalidate(); setRevision(value); }} onAnswer={value => { if (value.trim()) void propose(value); }} onRestart={() => invalidate(true)} /> : <>
      <p>자료원과 대상·지표·기간·비교 기준을 확인해 주세요. 승인 후 근거 기반 브리핑을 작성하며, 기사 작성·발행은 하지 않습니다.</p>
      <details><summary>제안한 조건과 제공 범위 설명</summary><ul>{plan.proposals.map((p, i) => <li key={i}>{p}</li>)}</ul></details>
      {!!Object.keys(plan.field_errors).length && <div className="clarification" role="status"><strong>처음 계획에서 확인할 내용</strong><ul>{Object.values(plan.field_errors).map((v, i) => <li key={i}>{v}</li>)}</ul><p>조건을 고친 뒤 다시 승인하면 서버가 제공 여부를 검사합니다. 지원 범위 안내가 있으면 질문이나 자연어 수정 요청으로 계획을 다시 확인해 주세요.</p></div>}
      {plan.companies.length > draft.entities.length && <p>회사 후보: {plan.companies.map(c => `${c.name} (${c.stock_code})`).join(' · ')}. 아래 수정 요청에 정확한 회사명을 적어 주세요.</p>}
      <form onSubmit={execute}>{mode === 'snapshot' ? <><p>{question}</p><Conditions value={draft} /></> : <div className="condition-fields">
        <label className="condition-field">대상 {eventConditionKey(draft) !== eventConditionKey(plan.conditions) && <span className="modified-badge">조건 수정됨</span>}{draft.tool === 'employment' ? <select value={draft.entities.join('|')} onChange={e => change('entities', e.target.value.split('|'))}><option value={draft.entities.join('|')}>{draft.entities.join(' · ') || '대상 선택'}</option>{catalog?.entities.map(v => <option key={v} value={v}>{v}</option>)}<option value="서울특별시|전국 집계">서울특별시 · 전국 집계</option></select> : <input readOnly value={draft.entities.join(' · ')} />}<span className="field-help">{draft.tool === 'employment' ? '지역을 선택하거나 아래에 변경 내용을 적어 주세요.' : '회사 변경은 아래 자연어 수정 요청으로 공식 코드를 다시 확인합니다.'}</span></label>
        <fieldset className="condition-field"><legend>지표</legend>{metrics.map(m => <label className="research-metric" key={m}><input type="checkbox" checked={draft.metrics.includes(m)} onChange={e => change('metrics', e.target.checked ? [...draft.metrics, m] : draft.metrics.filter(v => v !== m))} />{m}</label>)}</fieldset>
        {field('start')}{field('end')}{draft.tool !== 'disclosures' && field('frequency', draft.tool === 'financials' ? ['연간', '분기'] : ['연간', '월간'])}
        {field('comparison', draft.tool === 'disclosures' ? ['접수일순', '종류별'] : ['증감 폭', '증감률'])}
        {draft.tool !== 'disclosures' && field('comparison_period', ['전기', '전년 동기', '시작·종료'])}
        {draft.tool === 'financials' && <>{field('statement_basis', ['연결', '별도'])}{field('amount_basis', ['당기', '누적'])}</>}
        {draft.tool === 'employment' && field('age_range', catalog?.ages ?? ['15-29세', '20-29세', '15-64세'])}
      </div>}
      <p className="field-help">{catalog?.notice} 기간 표기: 연간 2025 / 분기 2026-Q2 / 월간 2026-08 / 공시 2026-09-18</p>
      {revision.trim() && <p className="notice">작성한 수정 요청을 먼저 반영해 주세요.</p>}
      <button className="primary" disabled={!!busy || !draft.metrics.length || !!revision.trim() || !!plan.field_errors.scope || draft.tool === 'undetermined'}>{busy === 'execute' ? '조회·계산·AI 브리핑 작성 중…' : '이 조건으로 조회'}</button><p>승인 후에만 자료와 브리핑을 표시합니다. 다시 조회하거나 조건을 바꾸면 검토 상태는 초기화됩니다.</p></form>
      {mode === 'live' && (conversation.length >= 8 ? <p className="notice">질답·자연어 수정을 8회 진행했습니다. 아래 수정 입력 대신 조건 폼에서 편집하거나 원 질문부터 계획을 다시 제안받아 주세요.</p> : <form className="research-refinement" onSubmit={e => { e.preventDefault(); void propose(revision); }}><label>계획을 말로 수정하기<textarea maxLength={1000} value={revision} placeholder="예: 현대자동차 별도 기준으로 바꾸고, 최근 두 분기의 영업이익을 비교해 줘." onChange={e => { invalidate(); setRevision(e.target.value); }} /></label><button disabled={!!busy || !revision.trim()}>수정 요청 반영</button></form>)}
      </>}
      <Trace steps={plan.trace} />
    </section>}
    {result && <EventResults result={result} general={general} previous={previous} onGeneral={() => void compare()} busy={busy === 'general'} error={generalError} />}
  </main>;
}
