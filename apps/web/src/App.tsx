import { FormEvent, useState } from "react";
import type { AnalysisResponse } from "./types";

const samples = [
  "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?",
  "삼성전자의 최근 실적은 악화됐는가?",
];

function App() {
  const [question, setQuestion] = useState(samples[0]);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/v1/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode: "mock" }),
      });

      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "분석 요청에 실패했습니다.");
      }

      setResult((await response.json()) as AnalysisResponse);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NewsTech Initiatives 2026 · 실습용 프로토타입</p>
          <h1>뉴스룸 데이터 에이전트</h1>
        </div>
        <span className="mode">모의 자료 모드</span>
      </header>

      <section className="question-panel" aria-labelledby="question-title">
        <div className="section-heading">
          <span>01</span>
          <div>
            <h2 id="question-title">취재 질문</h2>
            <p>에이전트가 어떤 공식 자료와 조건을 선택하는지 확인해 보세요.</p>
          </div>
        </div>

        <div className="sample-list" aria-label="실습 질문 예시">
          {samples.map((sample) => (
            <button key={sample} type="button" onClick={() => setQuestion(sample)}>
              {sample}
            </button>
          ))}
        </div>

        <form onSubmit={submit}>
          <label htmlFor="question">질문 입력</label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={3}
          />
          <button className="primary" type="submit" disabled={loading || !question.trim()}>
            {loading ? "조건을 해석하는 중…" : "질문 분석"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      {!result ? (
        <section className="empty-state">
          <strong>아직 실행된 질문이 없습니다.</strong>
          <p>먼저 질문을 분석하면 선택한 자료원과 검증 근거가 이곳에 나타납니다.</p>
        </section>
      ) : (
        <div className="result-grid">
          <section className="card">
            <p className="step">02 · 질문 해석</p>
            <h2>{result.query_plan.selected_source.toUpperCase()}</h2>
            <p>{result.query_plan.selection_reason}</p>
            <dl>
              <div><dt>대상</dt><dd>{result.query_plan.entity ?? "확인 필요"}</dd></div>
              <div><dt>지표</dt><dd>{result.query_plan.metric ?? "확인 필요"}</dd></div>
              <div><dt>기간</dt><dd>{result.query_plan.period ?? "확인 필요"}</dd></div>
            </dl>
            {result.query_plan.clarification_questions.length > 0 && (
              <div className="notice">
                <strong>실행 전 확인할 사항</strong>
                <ul>{result.query_plan.clarification_questions.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}
          </section>

          <section className="card">
            <p className="step">03 · 자료와 계산 근거</p>
            <h2>{result.evidence.source_name}</h2>
            <p>{result.evidence.table_or_report}</p>
            <dl>
              <div><dt>단위</dt><dd>{result.evidence.unit}</dd></div>
              <div><dt>조회 시점</dt><dd>{new Date(result.evidence.retrieved_at).toLocaleString("ko-KR")}</dd></div>
              <div><dt>계산식</dt><dd>{result.evidence.formula}</dd></div>
            </dl>
            <span className="data-mode">{result.evidence.data_mode} data</span>
          </section>

          <section className="card brief-card">
            <p className="step">04 · 검토용 브리핑</p>
            <h2>{result.brief.summary}</h2>
            <h3>확인된 내용</h3>
            <ul>{result.brief.verified_facts.map((item) => <li key={item}>{item}</li>)}</ul>
            <h3>단정하기 어려운 부분</h3>
            <ul>{result.brief.interpretation_limits.map((item) => <li key={item}>{item}</li>)}</ul>
            <h3>추가 취재 질문</h3>
            <ul>{result.brief.follow_up_questions.map((item) => <li key={item}>{item}</li>)}</ul>
            <span className="review-status">사람 검토 필요</span>
          </section>
        </div>
      )}
    </main>
  );
}

export default App;
