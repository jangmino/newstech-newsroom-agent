import type { CacheMetadata, ExecutionResponse } from "./types";

export function cacheLabel(cache: CacheMetadata) {
  return {
    miss: "공식 자료를 새로 조회했습니다.",
    hit: "보관된 공식 자료를 재사용했습니다.",
    coalesced: "같은 조건의 진행 중 조회 결과를 함께 사용했습니다.",
  }[cache.status];
}

export function CacheNotice({ result, compact = false }: {
  result: ExecutionResponse;
  compact?: boolean;
}) {
  const cache = result.cache;
  if (result.evidence.data_mode !== "live" || !cache) return null;
  return (
    <div className="notice" aria-label="공식 자료 재사용 안내">
      <strong>{cacheLabel(cache)}</strong>
      {cache.status === "hit" && <p>이번 승인에서는 외부 API를 다시 호출하지 않았습니다. 승인한 조건으로 계산과 브리핑을 새로 구성했습니다.</p>}
      {cache.status === "coalesced" && <p>중복 요청을 추가하지 않고 같은 자료를 기다렸습니다. 계산과 검토 표시는 이번 승인에만 적용됩니다.</p>}
      {!compact && <p>원자료 조회 시각: {new Date(result.evidence.retrieved_at).toLocaleString("ko-KR")}</p>}
      <p>재사용 기한: {new Date(cache.expires_at).toLocaleString("ko-KR")}</p>
      {!compact && <p className="field-help">이 결과를 만든 시점의 안내입니다. 기한이 지나면 다음 승인 때 새로 조회합니다. 자료 재사용이 최신 내용이나 기사 사용을 보증하지는 않습니다.</p>}
    </div>
  );
}
