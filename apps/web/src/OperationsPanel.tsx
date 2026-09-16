import { useEffect, useRef, useState } from "react";
import type { ApiGet } from "./api";
import { validSnapshot } from "./SnapshotNotice";
import type { CallLimitSettings, OperationsStatus, ProviderState } from "./types";

const providerLabels = { gemini: "Gemini 질문 해석", opendart: "OpenDART 실제 자료", kosis: "KOSIS 실제 자료" };
const providerStates: Record<ProviderState, string> = {
  configured: "설정상 허용 · 실제 연결 미확인",
  disabled: "사용 꺼짐",
  missing_configuration: "필수 설정 부족 · 운영자 확인 필요",
};
const snapshotLabels = { opendart: "OpenDART 저장 자료", kosis: "KOSIS 저장 자료" };
const snapshotStates = { available: "사용 가능 · 파일 확인됨", disabled: "사용 꺼짐", unavailable: "사용 불가 · 파일 확인 필요" };

function integerIn(value: unknown, min: number, max: number): boolean {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
}

function validLimits(value?: CallLimitSettings): boolean {
  return !!value && integerIn(value.requests_per_minute, 1, 300)
    && integerIn(value.max_concurrent_requests, 1, 30);
}

function validStatus(value: unknown): value is OperationsStatus {
  if (!value || typeof value !== "object") return false;
  const data = value as OperationsStatus;
  return typeof data.checked_at === "string" && Number.isFinite(Date.parse(data.checked_at))
    && data.external_calls_made === false
    && (["gemini", "opendart", "kosis"] as const).every((source) =>
      ["disabled", "missing_configuration", "configured"].includes(data.providers?.[source]))
    && (["opendart", "kosis"] as const).every((source) => {
      const snapshot = data.snapshots?.[source];
      return snapshot?.status === "available" ? validSnapshot(snapshot.metadata, source)
        : !!snapshot && ["disabled", "unavailable"].includes(snapshot.status) && snapshot.metadata === null;
    })
    && data.cache?.scope === "process" && typeof data.cache.enabled === "boolean"
    && integerIn(data.cache.ttl_seconds, 1, 86400) && integerIn(data.cache.max_entries_per_source, 1, 256)
    && data.limits?.scope === "process" && data.limits.window_seconds === 60
    && validLimits(data.limits.gemini) && validLimits(data.limits.public_data_per_source);
}

export function OperationsPanel({ get }: { get: ApiGet }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<OperationsStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => { revision.current += 1; controller.current?.abort(); }, []);

  function close() {
    revision.current += 1;
    controller.current?.abort();
    setOpen(false);
    setStatus(null);
    setError(null);
    setBusy(false);
  }

  async function refresh() {
    const current = ++revision.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setOpen(true);
    setStatus(null);
    setError(null);
    setBusy(true);
    try {
      const response = await get<unknown>("/api/v1/operations", request.signal);
      if (current !== revision.current) return;
      if (!validStatus(response)) throw new Error("운영 상태 응답을 확인하지 못했습니다. ‘상태 다시 확인’을 눌러 주세요.");
      setStatus(response);
    } catch (caught) {
      if (current === revision.current) setError(caught instanceof Error
        ? caught.message : "운영 상태를 확인하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      if (current === revision.current) setBusy(false);
    }
  }

  return <div className="operations">
    <button type="button" aria-expanded={open} aria-controls="operations-panel"
      onClick={() => open ? close() : void refresh()}>
      {open ? "운영 상태 닫기" : "실습 운영 상태 보기"}
    </button>
    {open && <section id="operations-panel" className="card" aria-labelledby="operations-title" aria-busy={busy}>
      <p className="step">실습 준비 확인 · 읽기 전용</p>
      <h2 id="operations-title">실습 운영 상태</h2>
      <p>외부 API를 호출하지 않고 서버 설정과 저장 자료 파일만 확인합니다.
        실제 연결·키 유효성·잔여 할당량은 확인하지 않습니다.</p>
      <button type="button" disabled={busy} onClick={() => void refresh()}>상태 다시 확인</button>
      {busy && <p role="status">운영 상태를 확인하고 있습니다.</p>}
      {error && <p className="error request-error" role="alert">{error}</p>}
      {status && <>
        <p className="field-help">상태 확인 시각: {new Date(status.checked_at).toLocaleString("ko-KR")} · 자동 갱신 없음</p>
        <div className="operations-grid">
          <section aria-labelledby="provider-status-title">
            <h3 id="provider-status-title">질문 해석과 실제 자료 설정</h3>
            <dl>{(Object.keys(providerLabels) as (keyof typeof providerLabels)[]).map((source) =>
              <div key={source}><dt>{providerLabels[source]}</dt><dd>{providerStates[status.providers[source]]}</dd></div>)}</dl>
            <p className="field-help">모의 규칙·모의 자료는 별도로 사용할 수 있습니다. 설정상 허용되어도 지원 범위 안에서 질문과 조건을 확인해야 합니다.</p>
          </section>
          <section aria-labelledby="snapshot-status-title">
            <h3 id="snapshot-status-title">공식 저장 자료</h3>
            <dl>{(Object.keys(snapshotLabels) as (keyof typeof snapshotLabels)[]).map((source) => {
              const snapshot = status.snapshots[source];
              return <div key={source}><dt>{snapshotLabels[source]}</dt><dd>
                {snapshotStates[snapshot.status]}
                {snapshot.metadata && <>
                  <p>{snapshot.metadata.coverage}</p>
                  <p>원래 조회 시각: {new Date(snapshot.metadata.captured_at).toLocaleString("ko-KR")}</p>
                </>}
              </dd></div>;
            })}</dl>
            <p className="field-help">최신 조회가 아니며 이후 개정·정정을 반영하지 않습니다. 파일 확인은 기사 사용 승인이 아닙니다.</p>
          </section>
          <section aria-labelledby="cache-status-title">
            <h3 id="cache-status-title">공공자료 캐시 설정</h3>
            <dl>
              <div><dt>사용 여부</dt><dd>{status.cache.enabled ? "사용 켜짐" : "사용 꺼짐"}</dd></div>
              <div><dt>보관 시간</dt><dd>{status.cache.ttl_seconds}초</dd></div>
              <div><dt>자료원별 최대</dt><dd>{status.cache.max_entries_per_source}건</dd></div>
            </dl>
            <p className="field-help">실제 조회에 적용하는 설정이며 현재 저장 건수가 아닙니다. 모의 자료와 공식 저장 자료에는 적용하지 않습니다.</p>
          </section>
          <section aria-labelledby="limits-status-title">
            <h3 id="limits-status-title">호출 제한 설정</h3>
            <dl>
              <div><dt>Gemini</dt><dd>최근 60초 {status.limits.gemini.requests_per_minute}회 · 동시 {status.limits.gemini.max_concurrent_requests}회</dd></div>
              <div><dt>OpenDART·KOSIS 각각</dt><dd>최근 60초 {status.limits.public_data_per_source.requests_per_minute}회 · 동시 {status.limits.public_data_per_source.max_concurrent_requests}회</dd></div>
            </dl>
            <p className="field-help">외부 호출 시작 횟수 기준입니다. OpenDART의 두 연도 조회는 2회입니다. 캐시 재사용·같은 조회의 공유 대기에는 추가 공공자료 호출이 없습니다.</p>
          </section>
        </div>
        <aside className="notice">캐시와 호출 제한은 이 서버 프로세스 안에서만 적용합니다. 여러 서버·인스턴스가 공유하는 행사 전체 한도나 남은 사용량이 아닙니다. 서버를 재시작하면 초기화됩니다.</aside>
      </>}
      <p className="field-help">현재 질문·조건·결과·검토 표시는 유지됩니다. 자료와 브리핑은 조건을 승인한 뒤 표시합니다.</p>
    </section>}
  </div>;
}
