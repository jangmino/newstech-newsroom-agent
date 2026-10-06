import type { EventExecuteRequest, EventPlanRequest } from "./eventTypes";
import type { ApiErrorDetail, ExecuteRequest, PlanRequest } from "./types";
import type { ResearchExecuteRequest, ResearchPlanRequest } from "./researchTypes";

type PostBody = EventExecuteRequest | EventPlanRequest | PlanRequest | ExecuteRequest | ResearchPlanRequest | ResearchExecuteRequest;

export function withRequestReference(message: string, response?: Response): string {
  const id = response?.headers.get("X-Request-ID");
  return id && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)
    ? `${message} 문의용 요청 번호: ${id}` : message;
}

export class WorkshopAccessError extends Error {
  constructor(public unavailable: boolean, response?: Response) {
    super(withRequestReference(unavailable ? "행사 입장 설정을 확인하고 있습니다. 운영자에게 문의해 주세요." : "행사 접근코드를 다시 확인해 주세요. 이전 결과와 검토 표시는 초기화했습니다.", response));
  }
}

export async function postJson<T>(path: string, body: PostBody, signal: AbortSignal, code?: string | ((value: EventProgress) => void), onProgress?: (value: EventProgress) => void): Promise<T> {
  if (typeof code === "function") { onProgress = code; code = undefined; }
  if (!/^\/api\/v1\/(?:(?:research\/)?(?:plan|execute)|event\/(?:plan|execute|general))$/.test(path)) throw new Error("지원하지 않는 요청입니다.");
  let response: Response | undefined;
  const streaming = path.startsWith("/api/v1/event/") && !!onProgress;
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) controller.abort();
  let timedOut = false;
  const started = Date.now();
  let timer = streaming ? setTimeout(() => { timedOut = true; controller.abort(); }, 360_000) : undefined;
  try {
    try {
      response = await fetch(streaming ? `${path}/stream` : path, {
        method: "POST", headers: { "Content-Type": "application/json", ...(code ? { "X-Workshop-Code": code } : {}) },
        cache: "no-store", credentials: "omit", redirect: "error",
        body: JSON.stringify(body), signal: streaming ? controller.signal : signal,
      });
    } catch {
      throw new Error("요청을 보내지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
    }
    if (streaming && response.ok && response.headers.get("Content-Type")?.includes("application/x-ndjson")) return await readEventStream<T>(response, controller.signal, value => {
      if (value.request_limit_seconds !== undefined) {
        clearTimeout(timer);
        const remaining = Math.max(1, (value.request_limit_seconds + 60) * 1000 - (Date.now() - started));
        timer = setTimeout(() => { timedOut = true; controller.abort(); }, remaining);
      }
      onProgress!(value);
    });
    return await readJson<T>(response);
  } catch (error) {
    if (timedOut) throw new Error(withRequestReference('응답 대기 시간이 초과됐습니다. 자동 재요청하지 않았습니다. 입력을 확인해 주세요.', response));
    throw error;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal.removeEventListener('abort', abort);
  }
}

export async function getJson<T>(path: string, signal: AbortSignal, code?: string): Promise<T> {
  if (path !== "/api/v1/operations" && path !== "/api/v1/event/catalog") throw new Error("지원하지 않는 요청입니다.");
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET", headers: code ? { "X-Workshop-Code": code } : {},
      cache: "no-store", credentials: "omit", redirect: "error", signal,
    });
  } catch {
    throw new Error("상태를 확인하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
  }
  return readJson<T>(response);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: ApiErrorDetail } | null;
    const detail = payload?.detail;
    if (response.status === 401) throw new WorkshopAccessError(false, response);
    if (response.status === 503 && detail?.code === "workshop_access_unavailable") throw new WorkshopAccessError(true, response);
    if (detail?.message && detail.field_errors) {
      throw new Error(withRequestReference(errorDetailMessage(detail), response));
    }
    throw new Error(withRequestReference("요청을 처리하지 못했습니다. 입력한 내용은 유지됩니다. 다시 시도해 주세요.", response));
  }
  try {
    return await response.json() as T;
  } catch {
    throw new Error(withRequestReference("응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.", response));
  }
}

function errorDetailMessage(detail: ApiErrorDetail): string {
  const fields = detail.field_errors && typeof detail.field_errors === 'object' && !Array.isArray(detail.field_errors)
    ? Object.values(detail.field_errors).filter((value): value is string => typeof value === 'string') : [];
  const seconds = detail.retry_after_seconds;
  const waitHint = detail.code === 'public_data_rate_limited'
    && typeof seconds === 'number' && Number.isInteger(seconds) && seconds >= 1 && seconds <= 60
    ? `다시 조회할 수 있는 예상 시간은 약 ${seconds}초 뒤입니다. 다른 요청에 따라 달라질 수 있습니다.` : '';
  return [...new Set([detail.message, ...fields, waitHint].filter(Boolean))].join(' ');
}

export type ApiPost = <T>(path: string, body: PostBody, signal: AbortSignal, onProgress?: (value: EventProgress) => void) => Promise<T>;
export type ApiGet = <T>(path: string, signal: AbortSignal) => Promise<T>;

export interface EventProgress {
  stage: 'accepted' | 'waiting' | 'running' | 'source_wait' | 'retry_wait';
  provider: 'gemini' | 'opendart' | 'kosis' | null;
  elapsed_seconds: number;
  waited_seconds: number;
  queue_ahead?: number | null;
  wait_limit_seconds?: number;
  request_limit_seconds?: number;
}

export async function readEventStream<T>(response: Response, signal: AbortSignal, onProgress: (value: EventProgress) => void): Promise<T> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error(withRequestReference('진행 상태 연결을 확인하지 못했습니다. 자동 재요청하지 않았습니다.', response));
  const decoder = new TextDecoder();
  let buffer = '';
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    if (signal.aborted) throw new Error('요청을 취소했습니다.');
    while (true) {
      const { value, done } = await reader.read();
      if (signal.aborted) throw new Error('요청을 취소했습니다.');
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 4_000_000) throw new Error('응답 크기를 확인하지 못했습니다.');
      let boundary: number;
      while ((boundary = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 1);
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        const reference = response.headers.get('X-Request-ID');
        if (reference && event.request_id !== reference) throw new Error('진행 상태의 요청 번호가 일치하지 않습니다.');
        if (event.type === 'progress') {
          if (!['accepted', 'waiting', 'running', 'source_wait', 'retry_wait'].includes(event.stage)
            || ![null, 'gemini', 'opendart', 'kosis'].includes(event.provider)
            || !Number.isFinite(event.elapsed_seconds) || event.elapsed_seconds < 0
            || !Number.isFinite(event.waited_seconds) || event.waited_seconds < 0) throw new Error('진행 상태 형식이 올바르지 않습니다.');
          if ((event.queue_ahead !== undefined && event.queue_ahead !== null && (!Number.isInteger(event.queue_ahead) || event.queue_ahead < 0 || event.queue_ahead > 160))
            || (event.wait_limit_seconds !== undefined && (!Number.isFinite(event.wait_limit_seconds) || event.wait_limit_seconds <= 0 || event.wait_limit_seconds > 300))
            || (event.request_limit_seconds !== undefined && (!Number.isFinite(event.request_limit_seconds) || event.request_limit_seconds <= 0 || event.request_limit_seconds > 360))) throw new Error('진행 상태 형식이 올바르지 않습니다.');
          onProgress(event);
        } else if (event.type === 'result' && event.result) return event.result as T;
        else if (event.type === 'error' && typeof event.detail?.message === 'string') {
          throw new Error(withRequestReference(errorDetailMessage(event.detail), response));
        } else throw new Error('응답 형식이 올바르지 않습니다.');
      }
      if (done) break;
    }
    throw new Error(withRequestReference('연결이 끊겨 완료 여부를 확인하지 못했습니다. 자동 재요청하지 않았습니다. 입력을 확인한 뒤 다시 요청해 주세요.', response));
  } catch (error) {
    if (error instanceof SyntaxError || error instanceof TypeError) throw new Error(withRequestReference('진행 상태 연결이 끊겼거나 응답을 읽지 못했습니다. 자동 재요청하지 않았습니다.', response));
    throw error;
  } finally {
    signal.removeEventListener('abort', abort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
