import { FinancialSummary } from "./FinancialEvidence";
import { CacheNotice } from "./CacheNotice";
import { comparisonConditions } from "./resultComparison";
import type { CalculationResult, ExecutionResponse } from "./types";

function ResultSummary({ result, side }: { result: ExecutionResponse; side: "previous" | "current" }) {
  const { evidence, calculation, brief } = result;
  const title = side === "previous" ? "이전 승인 결과" : "이번 승인 결과";
  return (
    <article className="condition-result" aria-labelledby={`${side}-result-title`}>
      <h3 id={`${side}-result-title`}>{title}</h3>
      <p className="synthetic-label">{evidence.data_mode === "live" ? (calculation?.data_origin === "kosis" ? "공식 통계 실제 조회 · 사람 검토 필요" : "공식 공시 실제 조회 · 사람 검토 필요") : calculation ? "가상 수치 계산 · 공식 통계 아님" : "모의 결과 · 실제 조회·계산 전"}</p>
      <p className="result-summary">{brief.summary}</p>
      {result.financial_calculation && <FinancialSummary calculation={result.financial_calculation} />}
      <dl>
        <div><dt>자료원</dt><dd>{evidence.source_name}</dd></div>
        <div><dt>자료</dt><dd>{evidence.table_or_report}</dd></div>
        <div><dt>단위</dt><dd>{calculation ? `입력 ${calculation.input_unit} · 결과 ${calculation.result_unit}` : evidence.unit}</dd></div>
        <div><dt>{evidence.data_mode === "live" ? "자료 조회 완료 시각" : calculation ? "가상 자료 계산 시각" : "모의 자료 생성 시각"}</dt><dd>{new Date(evidence.retrieved_at).toLocaleString("ko-KR")}</dd></div>
        <div><dt>계산식</dt><dd>{evidence.formula}</dd></div>
      </dl>
      <CacheNotice result={result} compact />
      <details open>
        <summary>{title}의 주의사항과 해석 한계</summary>
        <ul>{[...new Set([...evidence.caveats, ...brief.interpretation_limits])].map((text) => <li key={text}>{text}</li>)}</ul>
      </details>
    </article>
  );
}

function RegionResult({ calculation, region }: { calculation: CalculationResult; region: string }) {
  const row = calculation.rows.find((item) => item.region === region);
  if (!row) return <>조회 대상에 포함되지 않음</>;
  return (
    <>
      <strong>{row.status === "calculated"
        ? `${row.rank}위 · ${row.change} ${calculation.result_unit}` : "계산 불가 · 순위 없음"}</strong>
      <span className="region-inputs">{calculation.start_year}년: {row.start_value === null ? "값 없음" : `${row.start_value} ${calculation.input_unit}`} → {calculation.end_year}년: {row.end_value === null ? "값 없음" : `${row.end_value} ${calculation.input_unit}`}</span>
      {row.reason && <span className="region-inputs">{row.reason}</span>}
    </>
  );
}

export function ConditionComparison({ previous, current }: {
  previous: ExecutionResponse;
  current: ExecutionResponse;
}) {
  const conditions = comparisonConditions(previous.query_plan, current.query_plan);
  const before = previous.calculation;
  const after = current.calculation;
  const official = before?.data_origin === "kosis" && after?.data_origin === "kosis";
  const regions = [...new Set([...(before?.rows ?? []), ...(after?.rows ?? [])].map((row) => row.region))].sort();
  return (
    <section className="card condition-comparison" aria-labelledby="condition-comparison-title">
      <p className="step">조건 비교 · 같은 질문의 두 번의 조회</p>
      <h2 id="condition-comparison-title">조건 변경 전후 비교</h2>
      <p>직전에 성공한 승인 결과와 이번 결과입니다. 어떤 조건을 바꿨고 결과가 어떻게 달라졌는지 살펴보세요.</p>
      <div className="comparison-scroll" role="region" aria-label="승인 조건 비교 표, 작은 화면에서는 좌우로 이동할 수 있습니다" tabIndex={0}>
        <table className="condition-comparison-table">
          <caption>승인 조건 비교</caption>
          <thead><tr><th scope="col">조건</th><th scope="col">이전 승인</th><th scope="col">이번 승인</th></tr></thead>
          <tbody>{conditions.map((row) => (
            <tr key={row.field} className={row.changed ? "changed-condition" : undefined}>
              <th scope="row">{row.label}{row.changed && <span className="modified">변경</span>}</th>
              <td>{row.before}</td><td>{row.after}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="condition-result-grid">
        <ResultSummary result={previous} side="previous" />
        <ResultSummary result={current} side="current" />
      </div>
      {before && after ? (
        <>
          <p className="notice">각 순위는 해당 조회 대상 안에서 매긴 순위입니다. 단위·지표·기간·대상·연령 등 기준이 다른 값은 그대로 대소 비교할 수 없습니다. 여러 조건을 바꿨다면 특정 조건 하나의 영향으로 단정하지 마세요.</p>
          <div className="comparison-scroll" role="region" aria-label={`${official ? "시도별" : "가상 지역별"} 결과 비교 표, 작은 화면에서는 좌우로 이동할 수 있습니다`} tabIndex={0}>
            <table className="condition-comparison-table">
              <caption>{official ? "시도별 결과 비교 · KOSIS 실제 조회" : "가상 지역별 결과 비교 · 공식 통계 아님"}</caption>
              <thead><tr><th scope="col">{official ? "시도" : "가상 지역"}</th><th scope="col">이전 결과</th><th scope="col">이번 결과</th></tr></thead>
              <tbody>{regions.map((region) => (
                <tr key={region}><th scope="row">{region}</th>
                  <td><RegionResult calculation={before} region={region} /></td>
                  <td><RegionResult calculation={after} region={region} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="field-help">각 결과 안에서 같은 순위는 동률입니다. 순위는 반올림 전 값으로 정하며, 표시값이 같아도 순위가 다를 수 있습니다. 계산 불가 지역은 순위에 포함하지 않습니다.</p>
          {[{ label: "이전 결과", calculation: before }, { label: "이번 결과", calculation: after }].map(({ label, calculation }) => calculation.warnings.length > 0 && (
            <div className="notice" key={label}><strong>{label}의 계산 주의사항</strong><ul>{calculation.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>
          ))}
        </>
      ) : current.financial_calculation && previous.financial_calculation
        ? <p className="notice">각 결과의 비교 기준과 단위를 확인해 주세요. 원 단위 증감 폭과 % 증감률은 서로 다른 값입니다.</p>
        : <p className="notice">원자료 숫자와 계산 결과가 없어 수치 변화는 비교하지 않습니다. 승인 조건과 조회 설계의 차이를 확인해 주세요.</p>}
      <p className="field-help">이전 결과의 검토 체크는 이어받지 않습니다. 아래에서 이번 결과를 새로 검토해 주세요. 두 결과 모두 실습용이며 사실 검증 완료나 기사 사용 승인이 아닙니다.</p>
      <a className="evidence-link" href="#review-title">이번 결과 검토하기</a>
    </section>
  );
}
