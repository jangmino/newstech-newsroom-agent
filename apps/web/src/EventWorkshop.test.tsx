import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import App from './App';
import type { ApiGet, ApiPost } from './api';
import type { EventConditions, EventExecuteRequest, EventPlan, EventResult, GeneralResponse } from './eventTypes';
import { exportReview, reviewComplete, type ReviewArtifact } from './EventReview';

const question = '서울의 청년 고용률은 최근 5년간 전국 집계와 비교해 어떻게 달라졌을까?';
const conditions: EventConditions = { tool: 'employment', entities: ['서울특별시', '전국 집계'], company_codes: [], metrics: ['고용률'], start: '2021', end: '2025', frequency: '연간', comparison: '증감 폭', comparison_period: '시작·종료', statement_basis: '연결', amount_basis: '당기', age_range: '15-29세' };
function plan(q = question): EventPlan { return { request_id: 'plan-1', question: q, conditions, model: 'test-model', proposals: ['공식 제공 기간을 확인해 주세요.'], field_errors: {}, companies: [], trace: [], snapshot_id: null, status: 'ready', clarification: null }; }
function result(request?: EventExecuteRequest): EventResult { return { request_id: 'result-1', question: request?.question ?? question, conditions: request?.conditions ?? conditions, data_mode: request?.mode ?? 'live', facts: [1, 2].map(i => ({ id: `F${i}`, entity: '서울특별시', metric: '고용률', period: `202${i}`, value: '45', unit: '%', kind: 'observation', source_urls: ['https://kosis.kr/statHtml/statHtml.do?tblId=official'], retrieved_at: '2026-09-18T00:00:00Z', formula: '원자료 값', details: {} })), caveats: ['원문 대조 필요'], coverage: 'complete', trace: [{ tool: 'KOSIS 공식 통계', status: 'complete', at: '2026-09-18T00:00:00Z', parameters: {}, note: '' }], cache: null, brief: { status: 'complete', model: 'test-model', generation_method: 'gemini', content: { summary: { text: '공식 근거 요약', evidence_ids: ['F1'] }, findings: [{ text: '관찰 내용', evidence_ids: ['F2'] }], limitations: ['원인 확인 필요'], follow_up_questions: ['추가 취재는?'] }, error: null, verification_status: 'review_required' }, generated_at: '2026-09-18T00:00:00Z', snapshot_id: null }; }
function setup(overrides?: (path: string, body: unknown) => Promise<unknown>) {
  const post = vi.fn(async (path: string, body: unknown) => {
    if (overrides) return overrides(path, body);
    if (path.endsWith('/plan')) return plan((body as { question: string }).question);
    if (path.endsWith('/general')) return { ...body as EventExecuteRequest, request_id: 'general-1', model: 'test-model', text: '일반 모델의 실제 응답', generated_at: '2026-09-18T00:01:00Z', instruction: '중립적인 입력', tools: [], cache: null, data_mode: 'live' } satisfies GeneralResponse;
    return result(body as EventExecuteRequest);
  });
  const get = vi.fn(async () => ({ snapshots: [{ id: 'seoul', title: '공식 저장 서울 사례', question, conditions, generated_at: '2026-09-18T00:00:00Z' }], entities: ['서울특별시', '전국 집계'], ages: ['15-29세', '20-29세', '15-64세'], notice: '제공 기간 확인' }));
  render(<App post={post as ApiPost} get={get as ApiGet} />); return { post, get };
}
async function propose() { fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' })); await screen.findByRole('button', { name: '이 조건으로 조회' }); }
async function approve() { fireEvent.click(screen.getByRole('button', { name: '이 조건으로 조회' })); return screen.findByRole('heading', { name: '나의 취재 검토 기록' }); }

test('participant screen has no mock choices and makes no model calls on entry', async () => {
  const { post } = setup(); await waitFor(() => expect(screen.getByRole('combobox', { name: '조회 자료' })).toBeTruthy());
  expect(post).not.toHaveBeenCalled(); expect(document.body.textContent).not.toMatch(/mock|모의 자료|모의 규칙/);
  await propose(); expect(screen.queryByRole('table')).toBeNull(); expect(screen.queryByText('공식 근거 요약')).toBeNull();
  await approve(); expect(screen.getByRole('table')).toBeTruthy();
  expect(post.mock.calls[1][1]).toMatchObject({ mode: 'live', approved: true, conditions });
});

test('edits hide results and human review; approved conditions are returned and compared', async () => {
  setup(); await propose(); await approve();
  fireEvent.change(screen.getByRole('textbox', { name: '사실 1 내용' }), { target: { value: '직접 확인한 사실' } });
  fireEvent.change(screen.getByRole('combobox', { name: '비교 기준' }), { target: { value: '증감률' } });
  expect(screen.queryByRole('table')).toBeNull(); expect(screen.queryByRole('textbox', { name: '사실 1 내용' })).toBeNull();
  expect(screen.getAllByText(/수정됨/).length).toBeGreaterThan(0);
  await approve(); expect((screen.getByRole('textbox', { name: '사실 1 내용' }) as HTMLTextAreaElement).value).toBe('');
  expect(screen.getByRole('heading', { name: '조건을 바꾸니 무엇이 달라졌을까?' })).toBeTruthy();
});

test('general model is a separate explicit call with exactly the approved conditions', async () => {
  const { post } = setup(); await propose(); await approve(); expect(post).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', { name: '실제 일반 모델 응답 비교하기' }));
  await screen.findByText('일반 모델의 실제 응답'); expect(post.mock.calls[2][0]).toBe('/api/v1/event/general'); expect(post.mock.calls[2][1]).toEqual(post.mock.calls[1][1]);
  expect(screen.getByText(/공공자료 도구·웹 검색 없음/)).toBeTruthy();
});

test('a new question starts a new comparison baseline', async () => {
  setup(); await propose(); await approve();
  fireEvent.change(screen.getByRole('textbox', { name: '취재 질문 입력' }), { target: { value: '부산의 고용 변화는 어떨까?' } });
  await propose(); await approve();
  expect(screen.queryByRole('heading', { name: '조건을 바꾸니 무엇이 달라졌을까?' })).toBeNull();
});

test('download button creates a JSON artifact with the current review and original evidence', async () => {
  setup(); await propose(); await approve();
  const create = vi.fn(() => 'blob:test-export');
  const revoke = vi.fn();
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.isConnected).toBe(true);
    expect(this.download).toBe('뉴스룸-실습-검토기록.json');
  });
  fireEvent.change(screen.getByRole('textbox', { name: '검토 판단의 이유' }), { target: { value: '원문 추가 확인' } });
  fireEvent.click(screen.getByRole('button', { name: '조건·근거·AI 원본·검토 기록 내려받기' }));
  expect(click).toHaveBeenCalledTimes(1);
  const blob = (create.mock.calls[0] as unknown as [Blob])[0];
  const text = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob); });
  const artifact = JSON.parse(text);
  expect(artifact.human_review.reason).toBe('원문 추가 확인');
  expect(artifact.result.conditions).toEqual(conditions);
  expect(artifact.result.facts).toHaveLength(2);
  click.mockRestore();
  await waitFor(() => expect(revoke).toHaveBeenCalled(), { timeout: 1500 });
  vi.unstubAllGlobals();
});

test('general error preserves grounded evidence', async () => {
  setup(async (path, body) => { if (path.endsWith('general')) throw new Error('모델 한도 초과'); return path.endsWith('plan') ? plan() : result(body as EventExecuteRequest); });
  await propose(); await approve(); fireEvent.click(screen.getByRole('button', { name: '실제 일반 모델 응답 비교하기' })); await screen.findByText('모델 한도 초과'); expect(screen.getByRole('table')).toBeTruthy();
});

test('unsupported catalog explanation blocks execution until plan is reconsidered', async () => {
  const { post } = setup(async () => ({ ...plan(), field_errors: { scope: '시도별 월간 고용률 자료가 없습니다.' } }));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' })); await screen.findByText('시도별 월간 고용률 자료가 없습니다.'); expect(screen.queryByRole('button', { name: '이 조건으로 조회' })).toBeNull(); expect(post).toHaveBeenCalledTimes(1);
});

test('snapshot needs selection and reapproval, without live plan calls', async () => {
  const { post } = setup(); await waitFor(() => expect(screen.getByRole('combobox', { name: '조회 자료' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: '조회 자료' }), { target: { value: 'snapshot' } });
  await waitFor(() => expect(within(screen.getByRole('combobox', { name: '공식 저장 사례' })).getByText('공식 저장 서울 사례')).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: '공식 저장 사례' }), { target: { value: 'seoul' } });
  expect(post).not.toHaveBeenCalled(); expect(screen.queryByRole('table')).toBeNull(); await approve(); expect(post.mock.calls[0][1]).toMatchObject({ mode: 'snapshot', snapshot_id: 'seoul', approved: true });
});

test('late result cannot restore evidence after question change', async () => {
  let resolve!: (v: EventResult) => void;
  setup(async path => path.endsWith('plan') ? plan() : new Promise<EventResult>(r => { resolve = r; }));
  await propose(); fireEvent.click(screen.getByRole('button', { name: '이 조건으로 조회' }));
  fireEvent.change(screen.getByRole('textbox', { name: '취재 질문 입력' }), { target: { value: '새로운 취재 질문' } });
  await act(async () => resolve(result())); expect(screen.queryByRole('table')).toBeNull();
});

test('review completion requires actual entries and valid evidence; export preserves original', () => {
  const r = result(); const a: ReviewArtifact = { facts: [{ text: '사실 하나', evidence_id: 'F1', checked: true }, { text: '사실 둘', evidence_id: 'F2', checked: true }], unsupported_interpretation: '원인은 모름', follow_up_questions: ['질문 하나', '질문 둘'], desk_check: '단위 확인', status: '실습 검토 완료', reason: '원문 대조', edited_brief: '내가 고친 내용' };
  expect(reviewComplete(a, r)).toBe(true); expect(reviewComplete({ ...a, facts: [{ ...a.facts[0], evidence_id: 'F999' }, a.facts[1]] }, r)).toBe(false);
  const exported = exportReview(r, null, a); expect(exported.result.brief.content?.summary.text).toBe('공식 근거 요약'); expect(exported.human_review.edited_brief).toBe('내가 고친 내용'); expect(exported.notice).toContain('기사 사용 승인이 아닙니다');
});

test('switching workshop parts resets question and review', async () => {
  setup(); await propose(); await approve(); fireEvent.click(screen.getByRole('button', { name: '2부 · 내 질문으로 조사하기' }));
  expect(screen.queryByRole('table')).toBeNull(); expect(screen.getByRole('heading', { name: '질문에서 근거 기반 브리핑까지' })).toBeTruthy();
});

test('queued progress can be cancelled without losing conditions or accepting late results', async () => {
  const post = vi.fn();
  post.mockResolvedValueOnce(plan());
  const get = vi.fn(async () => ({ snapshots: [], entities: ['서울특별시'], ages: ['15-29세'], notice: '공식 범위' }));
  render(<App post={post as ApiPost} get={get as ApiGet} />);
  await propose();
  let resolve!: (value: EventResult) => void;
  post.mockImplementationOnce((_path, _body, _signal, onProgress) => {
    onProgress({ stage: 'waiting', provider: 'gemini', elapsed_seconds: 12, waited_seconds: 10 });
    return new Promise<EventResult>(r => { resolve = r; });
  });
  fireEvent.click(screen.getByRole('button', { name: '이 조건으로 조회' }));
  await screen.findByText('요청 순서를 기다리고 있습니다.');
  fireEvent.click(screen.getByRole('button', { name: '요청 취소' }));
  expect((post.mock.calls[1][2] as AbortSignal).aborted).toBe(true);
  expect(screen.getByRole('button', { name: '이 조건으로 조회' }).hasAttribute('disabled')).toBe(false);
  await act(async () => resolve(result()));
  expect(screen.queryByRole('textbox', { name: '사실 1 내용' })).toBeNull();
  expect(screen.getByRole('textbox', { name: '시작 기간' })).toHaveProperty('value', '2021');
});


test('cancelling a refinement retains edited conditions and the refinement text', async () => {
  const post = vi.fn(); post.mockResolvedValueOnce(plan());
  const get = vi.fn(async () => ({ snapshots: [], entities: ['서울특별시'], ages: ['15-29세'], notice: '공식 범위' }));
  render(<App post={post as ApiPost} get={get as ApiGet} />);
  await propose();
  fireEvent.change(screen.getByRole('textbox', { name: '시작 기간' }), { target: { value: '2022' } });
  fireEvent.change(screen.getByRole('textbox', { name: '계획을 말로 수정하기' }), { target: { value: '부산으로 바꿔 줘' } });
  let resolve!: (value: EventPlan) => void;
  post.mockImplementationOnce(() => new Promise<EventPlan>(r => { resolve = r; }));
  fireEvent.click(screen.getByRole('button', { name: '수정 요청 반영' }));
  fireEvent.click(screen.getByRole('button', { name: '요청 취소' }));
  await act(async () => resolve(plan()));
  expect(screen.getByRole('textbox', { name: /시작 기간/ })).toHaveProperty('value', '2022');
  expect(screen.getByRole('textbox', { name: '계획을 말로 수정하기' })).toHaveProperty('value', '부산으로 바꿔 줘');
  expect(screen.queryByRole('table')).toBeNull();
});

function ambiguous(q = question, prompt = '실적 변화와 공시 중 무엇을 볼까요?'): EventPlan {
  return { ...plan(q), status: 'needs_clarification', conditions: { ...conditions, tool: 'undetermined', entities: ['삼성전자'], metrics: [], start: '', end: '' }, clarification: { question: prompt, choices: ['실적 변화', '투자·지분·소송 공시'] }, field_errors: { tool: prompt } };
}

test('two dialogue answers preserve the question and history until explicit approval', async () => {
  let step = 0;
  const { post } = setup(async (path, body) => {
    const request = body as { question: string };
    if (!path.endsWith('/plan')) return result(body as EventExecuteRequest);
    step++;
    if (step === 1) return ambiguous(request.question);
    if (step === 2) return { ...ambiguous(request.question, '어느 기간을 비교할까요?'), clarification: { question: '어느 기간을 비교할까요?', choices: ['최근 두 연도'] } };
    return { ...plan(request.question), conditions: { ...conditions, tool: 'financials', entities: ['삼성전자'], company_codes: ['00126380'], metrics: ['매출액', '영업이익'], start: '2024', end: '2025' } };
  });
  fireEvent.click(screen.getByRole('button', { name: '2부 · 내 질문으로 조사하기' }));
  expect(screen.getByRole('textbox', { name: '취재 질문 입력' })).toHaveProperty('value', '');
  fireEvent.change(screen.getByRole('textbox', { name: '취재 질문 입력' }), { target: { value: '삼성전자의 최근 재무 이슈?' } });
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByText('실적 변화와 공시 중 무엇을 볼까요?');
  expect(screen.queryByRole('checkbox', { name: '고용률' })).toBeNull();
  expect(screen.queryByRole('textbox', { name: '시작 기간' })).toBeNull();
  expect(screen.queryByRole('button', { name: '이 조건으로 조회' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '실적 변화' }));
  await screen.findByText('어느 기간을 비교할까요?');
  fireEvent.change(screen.getByRole('textbox', { name: '직접 답변하기' }), { target: { value: '2024년과 2025년을 비교해 줘' } });
  fireEvent.click(screen.getByRole('button', { name: '답변 보내기' }));
  await screen.findByRole('button', { name: '이 조건으로 조회' });
  expect(post.mock.calls[2][1]).toMatchObject({ question: '삼성전자의 최근 재무 이슈?', revision: '2024년과 2025년을 비교해 줘', conversation: [
    { question: '실적 변화와 공시 중 무엇을 볼까요?', answer: '실적 변화' },
    { question: '어느 기간을 비교할까요?', answer: '2024년과 2025년을 비교해 줘' },
  ] });
  expect(post).toHaveBeenCalledTimes(3);
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.getByRole('checkbox', { name: '매출액' })).toBeTruthy();
  await approve();
  expect(post.mock.calls[3][1]).toMatchObject({ approved: true, conditions: { tool: 'financials', entities: ['삼성전자'], start: '2024', end: '2025' } });
});

test('a failed answer preserves text and does not duplicate conversation on retry', async () => {
  let n = 0;
  const { post } = setup(async () => { n++; if (n === 2) throw new Error('질문 해석 일시 오류'); return n === 1 ? ambiguous() : plan(); });
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('textbox', { name: '직접 답변하기' });
  fireEvent.change(screen.getByRole('textbox', { name: '직접 답변하기' }), { target: { value: '실적 변화' } });
  fireEvent.click(screen.getByRole('button', { name: '답변 보내기' }));
  await screen.findByText('질문 해석 일시 오류');
  expect(screen.getByRole('textbox', { name: '직접 답변하기' })).toHaveProperty('value', '실적 변화');
  fireEvent.click(screen.getByRole('button', { name: '답변 보내기' }));
  await screen.findByRole('button', { name: '이 조건으로 조회' });
  expect(post.mock.calls[2][1]).toEqual(post.mock.calls[1][1]);
});

test('cancelling an answer retains the question and answer and ignores its late plan', async () => {
  let resolve!: (value: EventPlan) => void;
  let n = 0;
  setup(async () => ++n === 1 ? ambiguous() : new Promise<EventPlan>(r => { resolve = r; }));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('button', { name: '실적 변화' });
  fireEvent.click(screen.getByRole('button', { name: '실적 변화' }));
  fireEvent.click(screen.getByRole('button', { name: '요청 취소' }));
  await act(async () => resolve(plan()));
  expect(screen.getByRole('textbox', { name: '직접 답변하기' })).toHaveProperty('value', '실적 변화');
  expect(screen.queryByRole('button', { name: '이 조건으로 조회' })).toBeNull();
});

test('changing the original question discards dialogue and a late reply', async () => {
  let resolve!: (value: EventPlan) => void;
  let n = 0;
  setup(async () => ++n === 1 ? ambiguous() : new Promise<EventPlan>(r => { resolve = r; }));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('button', { name: '실적 변화' });
  fireEvent.click(screen.getByRole('button', { name: '실적 변화' }));
  fireEvent.change(screen.getByRole('textbox', { name: '취재 질문 입력' }), { target: { value: '부산의 취업자 수' } });
  await act(async () => resolve(plan()));
  expect(screen.queryByRole('textbox', { name: '직접 답변하기' })).toBeNull();
  expect(screen.queryByRole('button', { name: '이 조건으로 조회' })).toBeNull();
});

test('unsupported combination offers narrowing without a misleading approval form', async () => {
  const { post } = setup(async () => ({ ...ambiguous(), status: 'unsupported', proposals: ['기업 실적과 고용의 인과관계 분석은 지원 범위 밖입니다.'], clarification: { question: '실적만 조사할까요?', choices: ['실적만 조사'] }, field_errors: { scope: '자료 결합 미지원' } }));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('button', { name: '실적만 조사' });
  expect(screen.getByText('기업 실적과 고용의 인과관계 분석은 지원 범위 밖입니다.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '이 조건으로 조회' })).toBeNull();
  expect(post).toHaveBeenCalledTimes(1);
});

test('dialogue limit stops further model calls and allows an explicit reset', async () => {
  const { post } = setup(async () => ambiguous());
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  for (let i = 0; i < 8; i++) {
    const choice = await screen.findByRole('button', { name: '실적 변화' });
    await waitFor(() => expect(choice.hasAttribute('disabled')).toBe(false));
    fireEvent.click(choice);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(i + 2));
  }
  await screen.findByRole('button', { name: '질답 다시 시작' });
  expect(screen.queryByRole('button', { name: '답변 보내기' })).toBeNull();
  expect(post).toHaveBeenCalledTimes(9);
  fireEvent.click(screen.getByRole('button', { name: '질답 다시 시작' }));
  expect(screen.getByRole('textbox', { name: '취재 질문 입력' })).toHaveProperty('value', question);
  expect(screen.queryByText(/함께 확인한 내용/)).toBeNull();
});

test('switching to official snapshots clears dialogue and still requires approval', async () => {
  const { post } = setup(async (path, body) => path.endsWith('/plan') ? ambiguous() : result(body as EventExecuteRequest));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('button', { name: '실적 변화' });
  fireEvent.click(screen.getByRole('button', { name: '실적 변화' }));
  await screen.findByText('함께 확인한 내용 (1회)');
  fireEvent.change(screen.getByRole('combobox', { name: '조회 자료' }), { target: { value: 'snapshot' } });
  expect(screen.queryByText(/함께 확인한 내용/)).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: '공식 저장 사례' }), { target: { value: 'seoul' } });
  expect(post).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('table')).toBeNull();
  await approve();
  expect(post.mock.calls[2][1]).toMatchObject({ mode: 'snapshot', approved: true, snapshot_id: 'seoul' });
});
