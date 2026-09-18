import { useState } from 'react';
import type { EventResult, GeneralResponse } from './eventTypes';

export interface ReviewArtifact {
  facts: { text: string; evidence_id: string; checked: boolean }[];
  unsupported_interpretation: string; follow_up_questions: string[]; desk_check: string;
  status: '검토 중' | '추가 확인 필요' | '보류' | '실습 검토 완료'; reason: string; edited_brief: string;
}
export function reviewComplete(a: ReviewArtifact, result: EventResult): boolean {
  return a.facts.length === 2 && a.facts.every(f => f.text.trim() && f.checked && result.facts.some(r => r.id === f.evidence_id)) && !!a.unsupported_interpretation.trim() && a.follow_up_questions.length === 2 && a.follow_up_questions.every(v => v.trim()) && !!a.desk_check.trim() && !!a.reason.trim();
}
export function exportReview(result: EventResult, general: GeneralResponse | null, artifact: ReviewArtifact) {
  return { format: 'newstech-workshop-review-v1', exported_at: new Date().toISOString(), notice: '실습 검토 기록입니다. 사실 검증 완료나 기사 사용 승인이 아닙니다.', result, general_response: general, human_review: artifact };
}
export function EventReview({ result, general }: { result: EventResult; general: GeneralResponse | null }) {
  const original = result.brief.content;
  const initial = original ? [original.summary.text, ...original.findings.map(f => f.text)].join('\n\n') : '';
  const [review, setReview] = useState<ReviewArtifact>({ facts: Array.from({ length: 2 }, () => ({ text: '', evidence_id: '', checked: false })), unsupported_interpretation: '', follow_up_questions: ['', ''], desk_check: '', status: '검토 중', reason: '', edited_brief: initial });
  function update(values: Partial<ReviewArtifact>) { setReview(old => ({ ...old, ...values, status: values.status ?? (old.status === '실습 검토 완료' ? '검토 중' : old.status) })); }
  function download() {
    const blob = new Blob([JSON.stringify(exportReview(result, general, review), null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = '뉴스룸-실습-검토기록.json'; document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="card human-review" aria-labelledby="event-review-title"><p className="step">05 · 사람의 검토와 수정</p><h2 id="event-review-title">나의 취재 검토 기록</h2>
    <p role="status" className="review-progress">{review.status} · 직접 확인한 사실 {review.facts.filter(f => f.checked).length}/2개</p>
    <p>AI 초안을 읽고 원문에서 확인한 내용과 추가 취재가 필요한 내용을 구분해 주세요.</p>
    {review.facts.map((fact, i) => <fieldset key={i} className="condition-field"><legend>직접 확인한 사실 {i + 1}</legend>
      <label>사실 {i + 1} 내용<textarea maxLength={1500} value={fact.text} onChange={e => update({ facts: review.facts.map((v, j) => i === j ? { ...v, text: e.target.value, checked: false } : v) })} /></label>
      <label>사실 {i + 1} 근거<select value={fact.evidence_id} onChange={e => update({ facts: review.facts.map((v, j) => i === j ? { ...v, evidence_id: e.target.value, checked: false } : v) })}><option value="">근거 선택</option>{result.facts.map(f => <option key={f.id} value={f.id}>{f.id} · {f.entity} · {f.metric} · {f.period}</option>)}</select></label>
      <label className="review-item"><input type="checkbox" disabled={!fact.text.trim() || !fact.evidence_id} checked={fact.checked} onChange={e => update({ facts: review.facts.map((v, j) => i === j ? { ...v, checked: e.target.checked } : v) })} />사실 {i + 1}의 원문과 조건을 직접 대조했습니다</label>
    </fieldset>)}
    <label>아직 근거가 부족한 해석 한 가지<textarea maxLength={1500} value={review.unsupported_interpretation} onChange={e => update({ unsupported_interpretation: e.target.value })} /></label>
    {review.follow_up_questions.map((v, i) => <label key={i}>후속 취재 질문 {i + 1}<textarea maxLength={1000} value={v} onChange={e => update({ follow_up_questions: review.follow_up_questions.map((x, j) => i === j ? e.target.value : x) })} /></label>)}
    <label>데스크에서 확인할 항목<textarea maxLength={1000} value={review.desk_check} onChange={e => update({ desk_check: e.target.value })} /></label>
    <details><summary>AI 원본과 내가 고친 초안</summary><h3>AI 원본</h3><p className="preserve-lines">{initial || '생성된 AI 초안이 없습니다.'}</p><label>내가 고친 브리핑<textarea rows={8} maxLength={12000} value={review.edited_brief} onChange={e => update({ edited_brief: e.target.value })} /></label><p>{review.edited_brief === initial ? '아직 수정하지 않았습니다.' : 'AI 원본에서 수정했습니다. 원본도 다운로드에 보존됩니다.'}</p></details>
    <label>검토 판단의 이유<textarea maxLength={1500} value={review.reason} onChange={e => update({ reason: e.target.value })} /></label>
    <label>검토 진행 상태<select value={review.status} onChange={e => update({ status: e.target.value as ReviewArtifact['status'] })}>{(['검토 중', '추가 확인 필요', '보류', '실습 검토 완료'] as const).map(s => <option key={s} disabled={s === '실습 검토 완료' && !reviewComplete(review, result)}>{s}</option>)}</select></label>
    <p className="field-help">사실 두 개의 원문 대조와 나머지 기록을 작성하면 ‘실습 검토 완료’를 선택할 수 있습니다. 기록을 고치면 완료 표시가 해제됩니다.</p>
    <button onClick={download}>조건·근거·AI 원본·검토 기록 내려받기</button><p className="notice">실습 검토 완료는 기사 사용 승인이 아닙니다. 기록은 이 화면에만 있으며, 질문·조건·자료 변경과 새로고침 시 초기화됩니다. 필요한 기록은 먼저 내려받으세요.</p>
  </section>;
}
