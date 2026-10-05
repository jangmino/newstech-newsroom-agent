import type { CitedText } from './researchTypes';
import type { EventConditions, EventResult, GeneralResponse, TraceStep } from './eventTypes';
import { InvestigationView } from './InvestigationView';
import { EventReview } from './EventReview';
export const labels: Record<keyof EventConditions, string> = { tool: '자료 도구', entities: '대상', company_codes: '공식 회사 코드', metrics: '지표', start: '시작 기간', end: '종료 기간', frequency: '주기', comparison: '비교 기준', comparison_period: '비교 기간', statement_basis: '재무제표 기준', amount_basis: '당기·누적', age_range: '연령' };
export const toolLabels = { financials: 'OpenDART 기업 실적', disclosures: 'OpenDART 기업 공시', employment: 'KOSIS 고용 통계', undetermined: '자료원 확인 필요', births: 'KOSIS 출생 회복', migration: 'KOSIS 청년 이동', prices: 'KOSIS 물가', compensation: 'OpenDART 보수 비교', business_mix: 'OpenDART 성장 구조' };
export function Conditions({ value, comparisonOnly = false }: { value: EventConditions; comparisonOnly?: boolean }) { return <dl className="approved-conditions">{Object.entries(value).filter(([k]) => !(['statement_basis', 'amount_basis'].includes(k) && value.tool !== 'financials') && !(k === 'age_range' && !['employment', 'migration'].includes(value.tool)) && !(k === 'company_codes' && !['financials', 'disclosures'].includes(value.tool))).map(([k, v]) => <div key={k}><dt>{k === 'tool' && comparisonOnly ? '비교 조건의 자료원' : labels[k as keyof EventConditions]}</dt><dd>{k === 'tool' ? <>{toolLabels[value.tool]}{comparisonOnly && ' · 이 응답에서는 사용하지 않음'}</> : Array.isArray(v) ? v.join(' · ') : v}</dd></div>)}</dl>; }
function GeneralInput({ general }: { general: GeneralResponse }) {
  return <details><summary>일반 응답에 전달한 질문·조건·지시문</summary>
    {general.data_mode === 'snapshot' && <p className="field-help">사전 생성 당시의 입력입니다. 지금 모델을 새로 호출한 것이 아닙니다.</p>}
    <h4>전달한 취재 질문</h4><p>{general.question}</p>
    <h4>전달한 비교 조건</h4>
    <p>근거 기반 브리핑과 조사 범위를 맞추기 위한 조건입니다. 자료원 이름은 조건에 포함되지만, 해당 자료를 조회하는 도구나 조회 수치·계산 결과는 일반 모델에 제공하지 않습니다.</p>
    <Conditions value={general.conditions} comparisonOnly />
    <details><summary>질문·조건 전체 구조 보기 (JSON)</summary>
      <p className="field-help">응답에 기록된 질문·승인 조건을 전송 형식으로 표시합니다. 위 표에서 생략한 공통 필드도 포함합니다.</p>
      <pre className="preserve-lines">{JSON.stringify({ question: general.question, approved_conditions: general.conditions }, null, 2)}</pre>
    </details>
    <h4>모델에 전달한 시스템 지시문</h4>
    <p className="field-help">아래 지시문과 위의 질문·조건을 함께 전달했습니다.</p>
    <pre className="preserve-lines">{general.instruction}</pre>
  </details>;
}
export function Trace({ steps }: { steps: TraceStep[] }) { const status = { complete: '완료', cached: '재사용', failed: '실패', partial: '일부 확인', empty: '0건' }; return <details><summary>실제로 실행한 단계 보기</summary><p>도구·공개 조건·실행 결과를 기록합니다. AI의 내부 사고 과정은 아닙니다.</p><ol>{steps.map((s, i) => <li key={i}><strong>{s.tool} · {status[s.status]}</strong> · {new Date(s.at).toLocaleString('ko-KR')}<p>{s.note}</p><dl>{Object.entries(s.parameters).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></li>)}</ol></details>; }
function Cite({ value }: { value: CitedText }) { return <>{value.text} {value.evidence_ids.map(id => <a key={id} href={`#event-${id}`}>[{id}] </a>)}</>; }
export function EventResults({ result, general, previous, onGeneral, busy, error }: { result: EventResult; general: GeneralResponse | null; previous: EventResult | null; onGeneral: () => void; busy: boolean; error: string }) {
  const content = result.brief.content;
  // Some model responses contain literal newline escapes; normalize only the display text.
  const generalText = general?.text.replace(/\\r\\n|\\n|\\r/g, '\n');
  return <div className="research-results">
    {previous && <section className="card"><h2>조건을 바꾸니 무엇이 달라졌을까?</h2><div className="response-grid"><div><h3>직전 승인 결과</h3><Conditions value={previous.conditions} /><p>{previous.brief.content?.summary.text ?? '브리핑 없음'}</p></div><div><h3>이번 승인 결과</h3><Conditions value={result.conditions} /><p>{content?.summary.text ?? '브리핑 없음'}</p></div></div><p>자료·기간이 다르면 숫자를 직접 차감해 비교하지 않습니다. 바뀐 조건과 근거를 먼저 확인해 주세요.</p></section>}
    <section className="card"><p className="step">03 · 실제 모델 응답 비교</p><h2>일반 응답과 근거 기반 브리핑</h2><p>같은 질문·승인 조건으로, 같은 모델에 공공자료 도구 없이 별도로 답하도록 요청합니다. 챗봇 제품 전체의 성능 평가가 아닙니다.</p>
      <button disabled={busy} onClick={onGeneral}>{busy ? '일반 모델 응답을 받는 중…' : general ? '일반 모델에 다시 질문하기' : result.data_mode === 'snapshot' ? '저장된 실제 일반 응답 보기' : '실제 일반 모델 응답 비교하기'}</button>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="response-grid"><article><h3>일반 모델 응답 · 도구 없음</h3><p className="notice">질문과 승인 조건만 전달합니다. 공식 자료의 조회 수치·계산 결과는 전달하지 않으며, 공공자료 조회·웹 검색 도구도 사용하지 않습니다.</p>{general ? <><p className="preserve-lines">{generalText}</p><p className="field-help">{general.model} · {new Date(general.generated_at).toLocaleString('ko-KR')} · {general.data_mode === 'snapshot' ? '사전 생성한 실제 응답 재생' : '실제 호출'} · 공공자료 도구·웹 검색 없음</p><GeneralInput general={general} /></> : <p>버튼을 누르면 실제 응답을 받습니다. 모르는 내용이나 추가 확인 요청도 그대로 비교합니다.</p>}</article>
      <article><h3>조회 근거를 받은 AI 브리핑</h3><p className="field-help">{result.brief.model ?? '생성 전'} · {new Date(result.generated_at).toLocaleString('ko-KR')} · {result.data_mode === 'snapshot' ? '공식 저장 자료·사전 생성 브리핑' : result.data_mode === 'archive' ? '공식 저장 원자료 · 새 Gemini 브리핑' : '공식 조회 근거 사용'}</p>
        {result.brief.error && <p role="alert" className="error">{result.brief.error}</p>}
        {content && <><p className="response-summary preserve-lines"><Cite value={content.summary} /></p><h4>근거에서 관찰한 내용</h4><ul>{content.findings.map((f, i) => <li key={i}><Cite value={f} /></li>)}</ul><h4>해석의 한계</h4><ul>{content.limitations.map((v, i) => <li key={i}>{v}</li>)}</ul><h4>후속 취재 질문</h4><ul>{content.follow_up_questions.map((v, i) => <li key={i}>{v}</li>)}</ul></>}
      </article></div><p className="notice">두 응답 모두 사람의 원문 대조가 필요합니다. 근거 번호가 있다고 문장의 의미·인과관계까지 검증된 것은 아닙니다.</p>
    </section>
    {result.analysis && <InvestigationView analysis={result.analysis} />}
    <section className="card evidence-card"><p className="step">04 · 자료와 계산 근거</p><h2>{toolLabels[result.conditions.tool]}</h2><span className="data-mode">{result.data_mode === 'snapshot' ? '공식 저장 자료 · 최신 조회 아님' : result.data_mode === 'archive' ? '공식 저장 원자료 · 최신 재조회 아님' : '공식 실제 자료'} · {result.coverage === 'partial' ? '일부 범위만 확인' : result.coverage === 'empty' ? '해당 조건 0건' : '선택 범위 확인'}</span><h3>승인된 조회 조건</h3><Conditions value={result.conditions} />
      {result.cache && <p className="notice">{result.cache.status === 'miss' ? (result.data_mode === 'archive' ? '공식 저장 원자료 새 계산' : '새로 조회') : '이전 계산 자료 재사용'} · 보관 {new Date(result.cache.stored_at).toLocaleString('ko-KR')} · 기한 {new Date(result.cache.expires_at).toLocaleString('ko-KR')}</p>}
      <Trace steps={result.trace} />
      <div className="research-table-wrap"><table><caption>공식 원자료와 코드 계산 · 근거 번호로 원문을 확인하세요.</caption><thead><tr><th>근거</th><th>대상·지표</th><th>기간</th><th>값·단위</th><th>계산·출처·시각</th></tr></thead><tbody>{result.facts.map(f => <tr key={f.id} id={`event-${f.id}`} tabIndex={-1}><th scope="row">{f.id}</th><td>{f.entity}<br />{f.metric}{f.rank != null && <p>{result.analysis ? '표시된 비교 범위' : '선택 범위 변화'} {f.rank}위</p>}</td><td>{f.period}</td><td>{/^-?\d+$/.test(f.value) ? BigInt(f.value).toLocaleString('ko-KR') : f.value} {f.unit}</td><td>{f.formula}<br />{f.source_urls.map((url, i) => /^https:\/\/(dart\.fss\.or\.kr|kosis\.kr)\//.test(url) ? <a key={url} href={url} target="_blank" rel="noreferrer">공식 원문 {i + 1} </a> : null)}<p>원래 조회 {new Date(f.retrieved_at).toLocaleString('ko-KR')}</p><details><summary>조회·계산·본문 상세</summary><dl>{Object.entries(f.details).map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="preserve-lines">{v}</dd></div>)}</dl></details></td></tr>)}</tbody></table></div><ul>{result.caveats.map((v, i) => <li key={i}>{v}</li>)}</ul>
    </section>
    <EventReview key={result.request_id} result={result} general={general} />
  </div>;
}
