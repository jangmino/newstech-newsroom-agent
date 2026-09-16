import type { CalculationResult } from "./types";

export function CalculationTable({ calculation, comparison }: {
  calculation: CalculationResult;
  comparison: string | null;
}) {
  return (
    <section className="calculation-panel" aria-labelledby="calculation-title">
      <h3 id="calculation-title">가상 원자료와 계산 결과</h3>
      <p className="synthetic-label">가상 지역·가상 숫자 · 공식 통계 아님</p>
      <p className="field-help">{calculation.ranking_method}. 표시값만 소수 둘째 자리로 반올림합니다. 표시값이 같아도 반올림 전 값이 다르면 순위가 다를 수 있습니다.</p>
      {calculation.warnings.length > 0 && (
        <div className="notice" role="status">
          <strong>계산하지 못한 값이 있습니다.</strong>
          <ul>{calculation.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </div>
      )}
      <div className="calculation-scroll" role="region" aria-label="가상 원자료와 계산 결과 표, 작은 화면에서는 좌우로 이동할 수 있습니다" tabIndex={0}>
        <table className="calculation-table">
          <caption>{calculation.start_year}~{calculation.end_year}년 시작·종료 값 비교</caption>
          <thead>
            <tr>
              <th scope="col">순위</th><th scope="col">가상 지역</th>
              <th scope="col">{calculation.start_year}년 ({calculation.input_unit})</th>
              <th scope="col">{calculation.end_year}년 ({calculation.input_unit})</th>
              <th scope="col">{comparison} ({calculation.result_unit})</th><th scope="col">확인 상태</th>
            </tr>
          </thead>
          <tbody>
            {calculation.rows.map((row) => (
              <tr key={row.region}>
                <td>{row.rank ?? "순위 없음"}</td><th scope="row">{row.region}</th>
                <td>{row.start_value ?? "값 없음"}</td><td>{row.end_value ?? "값 없음"}</td>
                <td>{row.change ?? "계산 불가"}</td>
                <td>{row.status === "calculated" ? "가상 값 계산 완료" : row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="field-help">자료 버전: {calculation.dataset_id}. 원자료와 계산 결과는 실제 취재에 사용할 수 없는 실습용 값입니다.</p>
    </section>
  );
}
