import type { SnapshotMetadata, SourceName } from "./types";

function publicSourceUrl(source: SourceName, url: string) {
  return source === "kosis"
    ? url === "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7015S"
    : source === "opendart" && /^https:\/\/dart\.fss\.or\.kr\/dsaf001\/main\.do\?rcpNo=\d{14}$/.test(url);
}

export function validSnapshot(snapshot: SnapshotMetadata | null | undefined, source: SourceName): snapshot is SnapshotMetadata {
  return !!snapshot && snapshot.source === source && typeof snapshot.snapshot_id === "string"
    && snapshot.snapshot_id.length > 0 && snapshot.snapshot_id.length <= 100
    && typeof snapshot.captured_at === "string" && Number.isFinite(Date.parse(snapshot.captured_at))
    && typeof snapshot.title === "string" && !!snapshot.title
    && typeof snapshot.coverage === "string" && !!snapshot.coverage
    && typeof snapshot.unit === "string" && !!snapshot.unit
    && Array.isArray(snapshot.source_urls) && snapshot.source_urls.length > 0
    && snapshot.source_urls.every((url) => typeof url === "string" && publicSourceUrl(source, url))
    && Array.isArray(snapshot.caveats) && snapshot.caveats.length > 0
    && snapshot.caveats.every((text) => typeof text === "string" && !!text);
}

export function SnapshotNotice({ snapshot, preview = false, compact = false }: {
  snapshot: SnapshotMetadata;
  preview?: boolean;
  compact?: boolean;
}) {
  return <aside className="notice" aria-label={preview ? "승인 전 저장 자료 안내" : "이 결과의 저장 자료 안내"}>
    <strong>공식 저장 자료 · 최신 조회 아님</strong>
    <p>{snapshot.title}</p>
    <p>저장 자료의 원래 조회 시각: {new Date(snapshot.captured_at).toLocaleString("ko-KR")}</p>
    <p>지원 범위: {snapshot.coverage} 단위: {snapshot.unit}</p>
    {!compact && <>
      <ul>{snapshot.source_urls.filter((url) => publicSourceUrl(snapshot.source, url)).map((url, index) =>
        <li key={url}><a className="evidence-link" href={url} target="_blank" rel="noreferrer">{snapshot.source === "kosis" ? "KOSIS 저장 자료 출처" : `OpenDART 저장 자료 출처 ${index + 1}`}</a></li>)}</ul>
      <ul>{snapshot.caveats.map((text) => <li key={text}>{text}</li>)}</ul>
    </>}
    <p>{preview ? "아직 자료와 브리핑을 표시하지 않았습니다. 저장 자료의 범위와 조건을 확인한 뒤 ‘이 조건으로 조회’를 눌러 주세요." : "이번 승인에서는 저장된 값을 사용했습니다. 실습 검토 확인은 사실 검증 완료나 기사 사용 승인이 아닙니다."}</p>
  </aside>;
}
