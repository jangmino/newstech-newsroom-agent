import type { ExecutionResponse } from "./types";

export function KosisEvidence({ result }: { result: ExecutionResponse }) {
  const rows = result.evidence.raw_values;
  const first = rows[0];
  // Link only to the supported official table, never to an arbitrary provider URL.
  const url = first?.org_id === "101" && first?.table_id === "DT_1DA7015S"
    ? "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1DA7015S" : null;
  const changedDates = [...new Set(rows.map((row) => String(row.last_changed_at)))];
  return (
    <section className="calculation-panel" aria-label="KOSIS 통계 출처와 연간 원자료">
      <h3>공식 통계 출처</h3>
      {url ? <a className="evidence-link" href={url} target="_blank" rel="noreferrer">KOSIS 원표 · 행정구역(시도)/연령별 경제활동인구</a> : <p>원표 링크를 확인해 주세요.</p>}
      <p className="field-help">출처: KOSIS(국가데이터처, 경제활동인구조사). 원표에서 승인한 연령·시도·연도를 선택해 값을 대조해 주세요.</p>
      <p>자료 최종수정일: {changedDates.join(", ")}</p>
      <p className="field-help">최종수정일은 통계 자료가 바뀐 날짜이며, 위의 자료 조회 완료 시각과 다릅니다.</p>
      <details>
        <summary>연간 원자료 {rows.length}개 값과 통계 코드 확인</summary>
        <p className="field-help">기관 {first?.org_id} · 통계표 {first?.table_id} · 항목 {first?.item_id} · 연령 {first?.age_code} · 연간 응답 코드 {first?.period_code}</p>
        <p className="field-help">중간 연도도 조회한 근거로 남깁니다. 아래 순위 계산은 승인한 시작·종료 연도만 비교합니다.</p>
        <div className="calculation-scroll" role="region" aria-label="KOSIS 연간 원자료 표, 작은 화면에서는 좌우로 이동할 수 있습니다" tabIndex={0}>
          <table className="calculation-table">
            <caption>15~29세 연간 고용률 · KOSIS 실제 조회</caption>
            <thead><tr><th scope="col">시도</th><th scope="col">연도</th><th scope="col">공표값 (%)</th><th scope="col">시도 코드</th><th scope="col">최종수정일</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={`${row.region_code}-${row.year}`}>
              <th scope="row">{row.region}</th><td>{row.year}</td><td>{row.raw_value}</td>
              <td>{row.region_code}</td><td>{row.last_changed_at}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
