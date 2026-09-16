import type { ExecutionResponse } from "./types";

export function ResponseComparison({ result, reviewProgress }: {
  result: ExecutionResponse;
  reviewProgress: string;
}) {
  const { brief, evidence, general_response: general, question, calculation } = result;
  const live = evidence.data_mode === "live";
  const kosis = live && calculation?.data_origin === "kosis";
  const rows = [
    ["조회 조건", "구체적인 조회 조건을 제시하지 않음", "참가자가 수정·승인한 조건 표시"],
    ["자료원", "직접 조회한 자료·출처 없음", kosis ? "KOSIS 공식 통계 실제 조회" : live ? "OpenDART 공시 실제 조회" : calculation ? "워크숍 가상 자료 · 공식 통계 아님" : `${evidence.source_name} 조회 계획 · 실제 조회 전`],
    ["단위·계산식", "제시하지 않음", kosis ? `입력 % · 결과 ${calculation.result_unit} · 적용한 계산식 표시` : live ? `원 단위 입력 · 결과 ${result.financial_calculation?.result_unit} · 적용한 계산식 표시` : calculation ? `입력 ${calculation.input_unit} · 결과 ${calculation.result_unit} · 가상 값에 적용한 계산식 표시` : `${evidence.unit} · 조건에 맞는 계산식 설계 표시`],
    ["조회 시각", "조회하지 않음", kosis ? "실제 조회 시각·자료 최종수정일 구분" : live ? "연도별 실제 조회 시각 표시" : calculation ? "가상 자료 계산 시각 표시 · 공식 조회 시각 아님" : "모의 자료 생성 시각 표시 · 실제 조회 시각 아님"],
    ["원자료·계산 결과", "없음", kosis ? "공표 고용률·변화값·순위·원표 링크 표시" : live ? "공시 금액·변화값·원문 링크 표시" : calculation ? "가상 입력값·변화값·순위·계산 불가 이유 표시" : "없음 · 실제 조회·계산 전"],
    ["사람의 검토", "설명에 필요한 근거를 추가로 확인", "승인 조건·계산식·해석 한계를 검토"],
  ];

  return (
    <section className="comparison-section" aria-labelledby="comparison-title">
      <header className="card comparison-intro">
        <p className="step">03 · 응답 비교</p>
        <h2 id="comparison-title">같은 질문의 두 응답</h2>
        <p className="comparison-question"><strong>질문</strong> {question}</p>
        <p>{live ? `일반 응답은 미리 작성한 모의 예시입니다. 근거 기반 브리핑은 승인 후 조회한 ${kosis ? "KOSIS 공식 통계" : "OpenDART 공시"}와 코드 계산을 사용합니다.` : "두 응답 모두 실습용 모의 예시입니다. 일반 응답은 미리 작성한 문장이며, 근거 기반 브리핑도 실제 공공데이터를 조회하지 않았습니다."}</p>
        <p className="field-help">답변에서 확인할 수 있는 조건과 근거를 비교해 보세요. 실제 모델의 응답 품질을 평가하는 화면은 아닙니다.</p>
      </header>

      <div className="comparison-grid">
        <article className="card response-card" aria-labelledby="general-title">
          <span className="data-mode">모의 예시 · 미리 작성한 응답</span>
          <h3 id="general-title">일반 응답 예시</h3>
          <p className="response-text">{general.text}</p>
          <h4>이 예시에서 더 확인할 내용</h4>
          <ul>
            <li>대상·지표·기간·비교 기준을 구체적으로 정했는가?</li>
            <li>설명을 뒷받침하는 원자료와 출처는 무엇인가?</li>
            <li>어떤 단위와 계산식으로 같은 결과를 확인할 수 있는가?</li>
          </ul>
          <p className="field-help">이 문장은 질문 유형별로 준비한 설명 예시입니다. 같은 유형에서는 조건을 바꿔도 문장이 같으며, 실제 모델 출력이나 조회 결과가 아닙니다.</p>
          <span className="review-status">사람 검토 필요</span>
        </article>

        <article className="card response-card" aria-labelledby="grounded-title">
          <span className="data-mode">{kosis ? "공식 통계 기반 브리핑 · 사람 검토 필요" : live ? "공식 공시 기반 브리핑 · 사람 검토 필요" : calculation ? "가상 수치 계산 · 공식 통계 아님" : "모의 브리핑 · 실제 조회 전"}</span>
          <h3 id="grounded-title">근거 기반 브리핑</h3>
          <p className="response-summary">{brief.summary}</p>
          <h4>{kosis ? "조회한 통계와 계산에서 확인된 내용" : live ? "조회한 공시와 계산에서 확인된 내용" : calculation ? "승인 조건과 가상 계산에서 확인된 내용" : "조건에서 확인된 내용"}</h4>
          <ul>{brief.verified_facts.map((item) => <li key={item}>{item}</li>)}</ul>
          <h4>단정하기 어려운 부분</h4>
          <ul>{brief.interpretation_limits.map((item) => <li key={item}>{item}</li>)}</ul>
          <h4>추가 취재 질문</h4>
          <ul>{brief.follow_up_questions.map((item) => <li key={item}>{item}</li>)}</ul>
          <a className="evidence-link" href="#evidence-title">승인된 조회 조건과 계산 근거 보기</a>
          <a className="review-progress" href="#review-title">{reviewProgress}</a>
          <p className="field-help">실습 검토 표시이며, 사실 검증 완료나 기사 사용 승인이 아닙니다.</p>
        </article>
      </div>

      <div className="card comparison-guide">
        <table>
          <caption>두 응답에서 무엇을 확인할 수 있나요?</caption>
          <thead>
            <tr><th scope="col">확인 항목</th><th scope="col">일반 응답 예시</th><th scope="col">근거 기반 브리핑</th></tr>
          </thead>
          <tbody>
            {rows.map(([label, generalValue, groundedValue]) => (
              <tr key={label}><th scope="row">{label}</th><td>{generalValue}</td><td>{groundedValue}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="field-help">{live ? "공식 자료 조회와 계산 완료가 사실 검증 완료나 기사 사용 승인을 뜻하지 않습니다. 원문과 해석을 직접 검토해 주세요." : calculation ? "근거 기반 브리핑은 직접 만든 가상 숫자를 계산했습니다. 실제 지역의 고용 상황이나 정책 효과를 설명하는 결과가 아닙니다." : "두 응답 모두 아직 원자료 숫자와 계산 결과가 없습니다. 실제 취재에 활용하기 전에는 원자료와 계산 결과를 별도로 검증해야 합니다."}</p>
      </div>
    </section>
  );
}
