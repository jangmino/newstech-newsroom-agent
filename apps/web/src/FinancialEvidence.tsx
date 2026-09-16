import type { ExecutionResponse, FinancialCalculation } from "./types";

// Keep exact backend decimal strings; never pass large KRW amounts through Number.
export function formatAmount(value: string): string {
  const [integer, fraction] = value.split(".");
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (fraction === undefined ? "" : `.${fraction}`);
}

export function FinancialSummary({ calculation }: { calculation: FinancialCalculation }) {
  return <p className="response-summary">{calculation.status === "calculated"
    ? `계산 결과: ${formatAmount(calculation.change!)} ${calculation.result_unit}`
    : calculation.reason}</p>;
}

export function FinancialEvidence({ result }: { result: ExecutionResponse }) {
  const calculation = result.financial_calculation;
  const snapshot = result.evidence.data_mode === "snapshot";
  if (!calculation) return null;
  return (
    <section className="calculation-panel" aria-label="공시 원자료와 계산 결과">
      <h3>공시 원자료와 계산 결과</h3>
      <FinancialSummary calculation={calculation} />
      <p className="field-help">원 단위 금액은 정수 그대로 표시합니다. 증감률은 소수 둘째 자리까지 반올림합니다. 순위를 매기지 않습니다.</p>
      <div className="calculation-scroll" role="region" aria-label="연도별 매출액과 공시 원문 표" tabIndex={0}>
        <table className="calculation-table">
          <caption>삼성전자 연간 연결 매출액 · OpenDART {snapshot ? "공식 저장 자료" : "실제 조회"}</caption>
          <thead><tr><th scope="col">사업연도</th><th scope="col">매출액 (원)</th><th scope="col">공시 원문</th><th scope="col">{snapshot ? "원래 조회 시각" : "조회 시각"}</th></tr></thead>
          <tbody>{result.evidence.raw_values.map((row) => {
            const receipt = String(row.receipt_no);
            const url = /^\d{14}$/.test(receipt) ? `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${receipt}` : null;
            return <tr key={String(row.year)}>
              <th scope="row">{row.year}년</th><td>{formatAmount(String(row.value))}</td>
              <td>{url ? <a href={url} target="_blank" rel="noreferrer">{row.year}년 사업보고서 · {receipt}</a> : "원문 확인 필요"}</td>
              <td>{new Date(String(row.retrieved_at)).toLocaleString("ko-KR")}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <details>
        <summary>계정과 공개 조회 인자 확인</summary>
        {result.evidence.raw_values.map((row) => <div key={String(row.year)}>
          <h4>{row.year}년 매출액</h4>
          <dl>
            <div><dt>계정</dt><dd>{row.account_name} · {row.account_id} · {row.statement_type}</dd></div>
            <div><dt>API 금액 원문</dt><dd>{row.raw_amount} {row.currency}</dd></div>
            <div><dt>회사·사업연도</dt><dd>{row.corp_code} · {row.bsns_year}</dd></div>
            <div><dt>보고서·연결 기준</dt><dd>{row.reprt_code} · {row.fs_div}</dd></div>
          </dl>
        </div>)}
      </details>
    </section>
  );
}
