import type { EventProgress } from './api';

export function EventProgressNotice({ progress, busy, onCancel }: { progress: EventProgress | null; busy: string; onCancel: () => void }) {
  const provider = progress?.provider ? { gemini: 'Gemini', opendart: 'OpenDART', kosis: 'KOSIS' }[progress.provider] : '';
  const waiting = progress?.stage === 'waiting';
  const title = waiting ? `${provider || '요청'} 실행 순서를 기다리고 있습니다.`
    : progress?.stage === 'retry_wait' ? '공급자 안내에 따라 잠시 기다린 뒤 한 번 더 요청합니다.'
    : progress?.stage === 'source_wait' ? '승인한 공식 자료를 조회하거나 같은 자료의 조회 완료를 기다리고 있습니다.'
    : busy === 'plan' ? '질문을 해석하고 조사 계획을 준비하고 있습니다.'
    : busy === 'general' ? '일반 모델 응답을 작성하고 있습니다.' : '공식 자료 조회·계산·브리핑을 진행하고 있습니다.';
  return <section className="notice" role="status" aria-live="polite">
    <strong>{title}</strong>
    <p>{provider && `${provider} · `}접수 후 {Math.floor(progress?.elapsed_seconds ?? 0)}초 · 대기 {Math.floor(progress?.waited_seconds ?? 0)}초</p>
    {waiting && progress?.queue_ahead != null && <p>{progress.queue_ahead > 0 ? `같은 자료원에서 먼저 기다리는 요청 ${progress.queue_ahead}개가 있습니다.` : '앞선 대기 요청은 없습니다. 호출 가능한 자리가 나면 진행합니다.'} 대기 순서는 자료원별로 달라집니다.</p>}
    <p>순서가 되면 자동으로 진행합니다. 다시 누르거나 새로고침하지 않아도 됩니다.{waiting && ' 현재 요청이 많아 수분이 걸릴 수 있습니다.'}</p>
    <p>대기는 최대 {progress?.wait_limit_seconds ?? 120}초, 전체 처리는 최대 {progress?.request_limit_seconds ?? 180}초입니다.</p>
    <button type="button" onClick={onCancel}>요청 취소</button>
  </section>;
}
