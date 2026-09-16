import type { OperationsStatus } from "../types";

export function exampleOperations(): OperationsStatus {
  return {
    checked_at: "2026-09-16T01:00:00Z", external_calls_made: false,
    providers: { gemini: "configured", opendart: "disabled", kosis: "missing_configuration" },
    snapshots: {
      opendart: { status: "unavailable", metadata: null },
      kosis: { status: "available", metadata: {
        snapshot_id: "test-kosis-snapshot", source: "kosis", title: "저장 자료 안내 예시",
        captured_at: "2026-09-15T00:00:00Z", coverage: "15~29세 · 17개 시도 · 2020~2024년",
        unit: "%", source_urls: ["https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7015S"],
        caveats: ["최신 조회가 아닙니다."],
      } },
    },
    cache: { scope: "process", enabled: true, ttl_seconds: 3600, max_entries_per_source: 64 },
    limits: {
      scope: "process", window_seconds: 60,
      gemini: { requests_per_minute: 30, max_concurrent_requests: 8 },
      public_data_per_source: { requests_per_minute: 30, max_concurrent_requests: 2 },
    },
  };
}
