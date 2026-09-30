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
afterEach(() => vi.unstubAllGlobals());
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
