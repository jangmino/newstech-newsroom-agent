import { useEffect, useRef, useState, type FormEvent } from "react";
import App from "./App";
import { getJson, postJson, withRequestReference, WorkshopAccessError, type ApiGet, type ApiPost } from "./api";
import type { WorkshopAccessStatus } from "./types";

const unavailableMessage = "행사 입장 설정을 확인하고 있습니다. 운영자에게 문의해 주세요.";

function validStatus(value: unknown): value is WorkshopAccessStatus {
  if (!value || typeof value !== "object") return false;
  const status = value as WorkshopAccessStatus;
  return typeof status.required === "boolean" && typeof status.available === "boolean"
    && (status.required || status.available);
}

export function WorkshopAccess() {
  const [status, setStatus] = useState<WorkshopAccessStatus | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState<"checking" | "entering" | null>("checking");
  const [error, setError] = useState<string | null>(null);
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);

  function invalidate() {
    revision.current += 1;
    controller.current?.abort();
    setCode(null);
    setInput("");
    setBusy(null);
  }

  async function checkStatus() {
    invalidate();
    setStatus(null);
    setError(null);
    setBusy("checking");
    const current = revision.current;
    const request = new AbortController();
    controller.current = request;
    let response: Response | undefined;
    try {
      response = await fetch("/api/v1/access", {
        cache: "no-store", credentials: "omit", redirect: "error", signal: request.signal,
      });
      const result: unknown = response.ok ? await response.json() : null;
      if (current !== revision.current) return;
      if (!validStatus(result)) throw new Error();
      setStatus(result);
      if (!result.available) setError(withRequestReference(unavailableMessage, response));
    } catch {
      if (current === revision.current) setError(withRequestReference("입장 상태를 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.", response));
    } finally {
      if (current === revision.current) setBusy(null);
    }
  }

  useEffect(() => {
    void checkStatus();
    return () => { revision.current += 1; controller.current?.abort(); };
  }, []);

  async function enter(event: FormEvent) {
    event.preventDefault();
    if (busy || !status?.required || !status.available) return;
    const submitted = input;
    setInput("");
    setError(null);
    if (!/^[A-Za-z0-9_-]{16,128}$/.test(submitted)) {
      setError("운영자가 안내한 접근코드를 그대로 입력해 주세요. 영문·숫자·밑줄·붙임표 16~128자이며 대소문자를 구분합니다.");
      return;
    }
    const current = ++revision.current;
    const request = new AbortController();
    controller.current = request;
    setBusy("entering");
    let response: Response | undefined;
    try {
      response = await fetch("/api/v1/access", {
        method: "POST", headers: { "X-Workshop-Code": submitted },
        cache: "no-store", credentials: "omit", redirect: "error", signal: request.signal,
      });
      if (current !== revision.current) return;
      if (response.status === 401) {
        setError(withRequestReference("접근코드가 일치하지 않습니다. 운영자가 안내한 코드로 다시 입력해 주세요.", response));
        return;
      }
      if (response.status === 503) {
        setStatus({ required: true, available: false });
        setError(withRequestReference(unavailableMessage, response));
        return;
      }
      const result: unknown = response.ok ? await response.json() : null;
      if (current !== revision.current) return;
      if (!validStatus(result) || !result.available) throw new Error();
      setStatus(result);
      setCode(result.required ? submitted : null);
    } catch {
      if (current === revision.current) setError(withRequestReference("입장을 확인하지 못했습니다. 연결을 확인한 뒤 코드를 다시 입력해 주세요.", response));
    } finally {
      if (current === revision.current) setBusy(null);
    }
  }

  const current = revision.current;
  function handleAccessError(caught: unknown, signal: AbortSignal) {
    if (current === revision.current && !signal.aborted && caught instanceof WorkshopAccessError) {
      invalidate();
      setStatus({ required: true, available: !caught.unavailable });
      setError(caught.message);
    }
  }

  const post: ApiPost = async (path, body, signal, onProgress) => {
    try {
      return await postJson(path, body, signal, code ?? undefined, onProgress);
    } catch (caught) {
      handleAccessError(caught, signal);
      throw caught;
    }
  };
  const get: ApiGet = async (path, signal) => {
    try {
      return await getJson(path, signal, code ?? undefined);
    } catch (caught) {
      handleAccessError(caught, signal);
      throw caught;
    }
  };

  if (status?.available && (!status.required || code)) {
    return <>
      {status.required && <div className="access-session" aria-label="행사 입장 상태">
        <span>행사 입장 확인 · 현재 탭에서만 유지됩니다.</span>
        <button type="button" onClick={() => { invalidate(); setError(null); }}>실습 나가기</button>
      </div>}
      <App post={post} get={get} />
    </>;
  }

  return <main className="shell access-shell">
    <header className="topbar"><div>
      <p className="eyebrow">NewsTech Initiatives 2026 · 실습용 프로토타입</p>
      <h1>뉴스룸 데이터 에이전트</h1>
    </div></header>
    <section className="card" aria-labelledby="access-title" aria-busy={busy !== null}>
      <p className="step">워크숍 입장</p>
      <h2 id="access-title">행사 접근코드 확인</h2>
      <p>운영자가 안내한 코드를 입력해 주세요. 입장한 뒤 질문과 조회 조건을 확인하고 승인하면 실습 결과를 볼 수 있습니다.</p>
      {busy === "checking" && <p role="status">입장 상태를 확인하고 있습니다.</p>}
      {error && <p className="error request-error" role="alert">{error}</p>}
      {status?.required && status.available && <form onSubmit={enter}>
        <div className="condition-field">
          <label htmlFor="workshop-code">행사 접근코드</label>
          <input id="workshop-code" type="password" value={input} maxLength={128} required
            autoComplete="off" autoCapitalize="none" spellCheck={false} autoFocus
            aria-describedby="access-help" disabled={busy !== null}
            onChange={(event) => setInput(event.target.value)} />
        </div>
        <button className="primary" type="submit" disabled={busy !== null || !input}>
          {busy === "entering" ? "입장 확인 중…" : "실습 입장"}
        </button>
      </form>}
      <p id="access-help" className="field-help">코드는 현재 탭에서만 사용합니다. 새로고침하거나 나가면 코드와 실습·검토 상태가 초기화됩니다.</p>
      {busy === "entering"
        ? <button type="button" onClick={() => { invalidate(); setError("입장을 취소했습니다."); }}>입장 취소</button>
        : <button type="button" disabled={busy !== null} onClick={() => void checkStatus()}>입장 상태 다시 확인</button>}
    </section>
  </main>;
}
