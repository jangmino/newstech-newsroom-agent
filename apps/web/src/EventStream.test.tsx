import { afterEach, expect, test, vi } from 'vitest';
import { postJson, readEventStream } from './api';
const id = '2157e5cf-59cb-48ee-aab7-b3de681911cb';
const progress = { type: 'progress', request_id: id, stage: 'waiting', provider: 'gemini', elapsed_seconds: 1, waited_seconds: 1 };
function response(events: unknown[], split = false) {
  const data = new TextEncoder().encode(events.map(e => JSON.stringify(e) + '\n').join(''));
  return new Response(new ReadableStream({ start(c) {
    if (split) for (let i = 0; i < data.length; i += 3) c.enqueue(data.slice(i, i + 3));
    else c.enqueue(data);
    c.close();
  } }), { headers: { 'Content-Type': 'application/x-ndjson', 'X-Request-ID': id } });
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

test('configured deadlines and provider queue counts reach the UI', async () => {
  const update = vi.fn();
  await readEventStream(response([{ ...progress, queue_ahead: 80, wait_limit_seconds: 240, request_limit_seconds: 300 }, { type: 'result', request_id: id, result: {} }]), new AbortController().signal, update);
  expect(update).toHaveBeenCalledWith(expect.objectContaining({ queue_ahead: 80, wait_limit_seconds: 240, request_limit_seconds: 300 }));
});

test.each([{ queue_ahead: -1 }, { queue_ahead: 161 }, { request_limit_seconds: 999999 }, { wait_limit_seconds: 0 }, { elapsed_seconds: -1 }])('invalid capacity fields cannot extend a browser request indefinitely %j', fields => {
  return expect(readEventStream(response([{ ...progress, ...fields }]), new AbortController().signal, vi.fn())).rejects.toThrow('진행 상태 형식');
});

test('repeated progress cannot reset the absolute browser deadline or send a duplicate', async () => {
  vi.useFakeTimers();
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  const fetch = vi.fn(async () => new Response(new ReadableStream({ start(c) { stream = c; } }), { headers: { 'Content-Type': 'application/x-ndjson', 'X-Request-ID': id } }));
  vi.stubGlobal('fetch', fetch);
  const request = postJson('/api/v1/event/plan', { question: '청년 고용 질문' }, new AbortController().signal, vi.fn());
  const rejected = expect(request).rejects.toThrow('응답 대기 시간이 초과');
  await vi.advanceTimersByTimeAsync(0);
  stream.enqueue(new TextEncoder().encode(JSON.stringify({ ...progress, wait_limit_seconds: 240, request_limit_seconds: 300 }) + '\n'));
  await vi.advanceTimersByTimeAsync(350_000);
  stream.enqueue(new TextEncoder().encode(JSON.stringify({ ...progress, wait_limit_seconds: 240, request_limit_seconds: 300 }) + '\n'));
  await vi.advanceTimersByTimeAsync(10_000);
  await rejected;
  expect(fetch).toHaveBeenCalledOnce();
});
test('progress and split Korean text are read until terminal result', async () => {
  const update = vi.fn();
  const r = await readEventStream(response([progress, { type: 'result', request_id: id, result: { text: '정상 결과' } }], true), new AbortController().signal, update);
  expect(r).toEqual({ text: '정상 결과' }); expect(update).toHaveBeenCalledOnce();
});
test('stream terminal error retains correlation', async () => {
  await expect(readEventStream(response([progress, { type: 'error', request_id: id, detail: { message: '선불 잔액을 확인해 주세요.' } }]), new AbortController().signal, vi.fn())).rejects.toThrow(id);
});
test('truncated stream is not interpreted as success or re-requested', async () => {
  await expect(readEventStream(response([progress]), new AbortController().signal, vi.fn())).rejects.toThrow('자동 재요청하지 않았습니다');
});
test('mismatched request reference rejected', async () => {
  await expect(readEventStream(response([{ ...progress, request_id: 'wrong' }]), new AbortController().signal, vi.fn())).rejects.toThrow('요청 번호');
});
test('abort cancels pending reader', async () => {
  const cancel = vi.fn(); const controller = new AbortController();
  const r = new Response(new ReadableStream({ cancel }));
  const promise = readEventStream(r, controller.signal, vi.fn());
  controller.abort();
  await expect(promise).rejects.toThrow('취소'); expect(cancel).toHaveBeenCalled();
});
test('event progress uses stream endpoint and existing access header once', async () => {
  const fetch = vi.fn(async () => response([{ type: 'result', request_id: id, result: { ok: true } }]));
  vi.stubGlobal('fetch', fetch);
  expect(await postJson('/api/v1/event/plan', { question: '청년 고용 질문' }, new AbortController().signal, 'test-code', vi.fn())).toEqual({ ok: true });
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0]).toEqual(['/api/v1/event/plan/stream', expect.objectContaining({ headers: expect.objectContaining({ 'X-Workshop-Code': 'test-code' }) })]);
});

test('stream and JSON errors show field guidance and request reference identically', async () => {
  const detail = { code: 'invalid_conditions', message: '조회 조건을 확인해 주세요.', field_errors: { period: '이 실습 앱은 한 번에 최대 93일을 조회합니다.', metrics: '지표를 선택해 주세요.' } };
  const expected = `${detail.message} ${detail.field_errors.period} ${detail.field_errors.metrics} 문의용 요청 번호: ${id}`;
  await expect(readEventStream(response([{ type: 'error', request_id: id, detail }]), new AbortController().signal, vi.fn())).rejects.toThrow(expected);
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 422, headers: { 'X-Request-ID': id } })));
  await expect(postJson('/api/v1/event/plan', { question: 'NAVER 공시' }, new AbortController().signal)).rejects.toThrow(expected);
});

test('malformed field guidance does not hide the stream error or leak object values', async () => {
  const detail = { message: '조건을 확인해 주세요.', field_errors: { period: '기간을 줄여 주세요.', bad: { internal: 'hidden' } } };
  await expect(readEventStream(response([{ type: 'error', request_id: id, detail }]), new AbortController().signal, vi.fn())).rejects.toThrow(`조건을 확인해 주세요. 기간을 줄여 주세요. 문의용 요청 번호: ${id}`);
});
