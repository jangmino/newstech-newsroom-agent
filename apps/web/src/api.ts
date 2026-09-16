import type { ApiErrorDetail, ExecuteRequest, PlanRequest } from "./types";

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

export async function postJson<T>(path: string, body: PlanRequest | ExecuteRequest, signal: AbortSignal, code?: string): Promise<T> {
  if (!/^\/api\/v1\/(plan|execute)$/.test(path)) throw new Error("지원하지 않는 요청입니다.");
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json", ...(code ? { "X-Workshop-Code": code } : {}) },
      cache: "no-store", credentials: "omit", redirect: "error",
      body: JSON.stringify(body), signal,
    });
  } catch {
    throw new Error("요청을 보내지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: ApiErrorDetail } | null;
    const detail = payload?.detail;
    if (response.status === 401) throw new WorkshopAccessError(false, response);
    if (response.status === 503 && detail?.code === "workshop_access_unavailable") throw new WorkshopAccessError(true, response);
    if (detail?.message && detail.field_errors) {
      const seconds = detail.retry_after_seconds;
      const waitHint = detail.code === "public_data_rate_limited"
        && typeof seconds === "number" && Number.isInteger(seconds) && seconds >= 1 && seconds <= 60
        ? `다시 조회할 수 있는 예상 시간은 약 ${seconds}초 뒤입니다. 다른 요청에 따라 달라질 수 있습니다.`
        : "";
      throw new Error(withRequestReference([detail.message, ...Object.values(detail.field_errors), waitHint].filter(Boolean).join(" "), response));
    }
    throw new Error(withRequestReference("요청을 처리하지 못했습니다. 입력한 내용은 유지됩니다. 다시 시도해 주세요.", response));
  }
  try {
    return await response.json() as T;
  } catch {
    throw new Error(withRequestReference("응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.", response));
  }
}

export type ApiPost = <T>(path: string, body: PlanRequest | ExecuteRequest, signal: AbortSignal) => Promise<T>;
