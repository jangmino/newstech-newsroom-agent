import type { InvestigationAnalysis } from './eventTypes';

export function InvestigationView({ analysis }: { analysis: InvestigationAnalysis }) {
  return <section className="card investigation-analysis" aria-labelledby="investigation-analysis-title">
    <p className="step">발견을 뒷받침하는 비교</p><h2 id="investigation-analysis-title">{analysis.title}</h2>
    <p className="field-help">{analysis.source_version} · 표와 비중은 코드로 계산했습니다.</p>
    <ul>{analysis.method.map(m => <li key={m}>{m}</li>)}</ul>
    {analysis.tables.map((table, i) => {
      const shares = table.title.includes('사업 구성') ? table.rows.filter(r => r[0] === table.rows.at(-1)?.[0]) : [];
      return <div className="analysis-section" key={table.title}>
        <h3>{table.title}</h3>
        {!!shares.length && <figure className="share-chart"><figcaption>{shares[0][0]}년 매출 비중 · 회사별 공식 분류</figcaption>{shares.map(r => <div className="share-row" key={r[1]}><span>{r[1]}</span><div className="share-track"><div style={{ width: `${Math.max(0, Math.min(100, Number(r[3]) || 0))}%` }} /></div><strong>{r[3]}%</strong></div>)}</figure>}
        <p className="notice">{table.note}</p>
        <details open={i === 0 || table.rows.length <= 10}><summary>비교표와 연결 근거 보기 · {table.rows.length}행</summary>
          <div className="research-table-wrap"><table><caption>{table.title}</caption><thead><tr>{table.columns.map(c => <th key={c} scope="col">{c}</th>)}</tr></thead><tbody>{table.rows.map((row, n) => <tr key={n}>{row.map((value, j) => j === 0 ? <th scope="row" key={j}>{value}</th> : <td key={j}>{/^-?\d+(\.\d+)?$/.test(value) && Math.abs(Number(value)) >= 1000 ? Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 4 }) : value}</td>)}</tr>)}</tbody></table></div>
          <details><summary>계산 근거 번호</summary><p>{table.evidence_ids.map(id => <a key={id} href={`#event-${id}`}>[{id}] </a>)}</p></details>
        </details>
      </div>;
    })}
    <p className="field-help">비교에서 발견한 차이가 곧 원인의 입증은 아닙니다. 원문과 추가 취재로 확인해 주세요.</p>
  </section>;
}
