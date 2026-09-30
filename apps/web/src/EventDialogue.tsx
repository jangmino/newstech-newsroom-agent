import type { EventClarification, EventDialogueTurn } from './eventTypes';

export function DialogueHistory({ turns }: { turns: EventDialogueTurn[] }) {
  if (!turns.length) return null;
  return <details className="dialogue-history"><summary>함께 확인한 내용 ({turns.length}회)</summary>
    <ol>{turns.map((turn, i) => <li key={i}><p><strong>확인 질문</strong> {turn.question}</p><p><strong>내 답변</strong> {turn.answer}</p></li>)}</ol>
  </details>;
}

export function EventDialogue({ clarification, explanations, unsupported, answer, busy, limitReached, onChange, onAnswer, onRestart }: {
  clarification: EventClarification; explanations: string[]; unsupported: boolean; answer: string; busy: boolean; limitReached: boolean;
  onChange: (value: string) => void; onAnswer: (value: string) => void; onRestart: () => void;
}) {
  return <div className="planning-dialogue">
    {unsupported && <p className="notice">현재 요청을 그대로 조사할 수 없습니다. 가능한 범위로 좁히거나 다른 질문을 선택해 주세요. 조건을 임의로 바꾸어 조회하지 않습니다.</p>}
    {explanations.map((text, i) => <p key={i}>{text}</p>)}
    <p className="dialogue-question">{clarification.question}</p>
    <p className="field-help">답변을 바탕으로 조사 방향을 구체화합니다. 아직 자료를 조회하거나 브리핑을 작성하지 않습니다.</p>
    {limitReached ? <><p role="status">한 질문에서 8회까지 답변을 이어갈 수 있습니다. 확인한 내용을 참고해 원 질문을 구체화하거나, 질답을 다시 시작해 주세요. ‘공식 저장 자료’로 실습을 이어갈 수도 있습니다.</p><button type="button" className="secondary" disabled={busy} onClick={onRestart}>질답 다시 시작</button></> : <>
      <div className="sample-list dialogue-choices" aria-label="확인 질문의 답변 선택지">{clarification.choices.map(choice => <button type="button" key={choice} disabled={busy} onClick={() => onAnswer(choice)}>{choice}</button>)}</div>
      <form onSubmit={e => { e.preventDefault(); onAnswer(answer); }}>
        <label>직접 답변하기<textarea rows={2} maxLength={1000} value={answer} onChange={e => onChange(e.target.value)} placeholder="궁금한 방향을 짧게 적어 주세요." /></label>
        <button className="primary" disabled={busy || !answer.trim()}>답변 보내기</button>
      </form>
    </>}
  </div>;
}
