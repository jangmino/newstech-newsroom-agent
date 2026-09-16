import { useState, type ReactNode } from "react";
import { ResponseComparison } from "./ResponseComparison";
import type { ExecutionResponse } from "./types";

type ReviewItem = "conditions" | "source" | "calculation" | "limits";

// Mounted only for one approved result; discarding that result discards these checks.
export function ReviewSession({ result, children }: {
  result: ExecutionResponse;
  children: ReactNode;
}) {
  const [checked, setChecked] = useState<ReviewItem[]>([]);
  const live = result.evidence.data_mode === "live";
  const kosis = live && result.calculation?.data_origin === "kosis";
  const items: { id: ReviewItem; title: string; description: string }[] = [
    {
      id: "conditions", title: "승인된 조회 조건",
      description: "대상·지표·기간·비교 기준과 추가 조건을 확인했습니다.",
    },
    {
      id: "source", title: "자료의 출처와 시각",
      description: kosis ? "KOSIS 원표·통계 코드·실제 조회 시각과 자료 최종수정일을 확인했습니다." : live ? "공시 원문·접수번호·연도별 실제 조회 시각을 확인했습니다." : "공식 자료를 조회하지 않은 모의 결과이며, 표시된 시각이 공식 자료 조회 시각이 아님을 확인했습니다.",
    },
    {
      id: "calculation", title: "원자료와 계산 근거",
      description: kosis ? "공표 고용률·%와 %p 단위·계산식·변화값 순위와 계산 불가 여부를 확인했습니다." : live ? "공시 매출액·원 단위·계산식과 비교 결과를 확인했습니다." : result.calculation
        ? "가상 입력값·단위·계산식·순위와 계산 불가 여부를 확인했습니다."
        : "원자료 숫자와 계산 결과가 없으며, 표시된 계산식은 조회 설계임을 확인했습니다.",
    },
    {
      id: "limits", title: "해석의 한계와 추가 취재",
      description: "브리핑의 해석 한계와 추가 취재 질문을 확인했습니다.",
    },
  ];
  const complete = checked.length === items.length;
  const status = complete ? "실습 검토 항목 확인 완료" : checked.length ? "실습 검토 중" : "실습 검토 전";
  const progress = `${status} · ${checked.length}/${items.length}개 확인`;

  function toggle(id: ReviewItem, selected: boolean) {
    setChecked((previous) => selected
      ? [...previous.filter((item) => item !== id), id]
      : previous.filter((item) => item !== id));
  }

  return (
    <>
      <ResponseComparison result={result} reviewProgress={progress} />
      {children}
      <section className="card human-review" aria-labelledby="review-title">
        <p className="step">05 · 사람의 검토</p>
        <h2 id="review-title">이 결과의 실습 검토</h2>
        <p>위의 승인 조건·자료·브리핑을 읽고, 직접 확인한 항목을 선택해 주세요. 선택은 언제든 해제할 수 있습니다.</p>
        <p className="review-progress" role="status" aria-live="polite" aria-atomic="true">{progress}</p>
        <fieldset className="review-checklist" aria-describedby="review-disclaimer review-reset-help">
          <legend>확인한 검토 항목</legend>
          {items.map((item) => (
            <label className="review-item" key={item.id}>
              <input type="checkbox" checked={checked.includes(item.id)}
                aria-labelledby={`review-${item.id}-label`} aria-describedby={`review-${item.id}-help`}
                onChange={(event) => toggle(item.id, event.target.checked)} />
              <span>
                <strong id={`review-${item.id}-label`}>{item.title}</strong>
                <span id={`review-${item.id}-help`}>{item.description}{item.id === "source" && live && result.cache && " 자료 재사용 여부와 원래 조회 시각·재사용 기한도 확인했습니다."}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <p id="review-disclaimer" className="notice">
          {complete && <strong>실습 검토 항목을 모두 확인했습니다. </strong>}
          이 표시는 참가자가 실습 항목을 확인했다는 뜻입니다. 사실 검증 완료나 기사 사용 승인이 아닙니다.
          {kosis ? "공식 통계도 원표·표본오차·지역 경계와 해석 검토가 필요하며, 일반 응답 예시는 취재 근거가 아닙니다." : live ? "공식 공시도 원문 대조와 해석 검토가 필요하며, 일반 응답 예시는 취재 근거가 아닙니다." : "가상 자료와 모의 응답은 실제 취재 근거로 사용할 수 없습니다."}
        </p>
        <p id="review-reset-help" className="field-help">검토 표시는 현재 화면에만 유지됩니다. 질문·조건 변경, 다시 분석·조회, 새로고침 시 초기화됩니다.</p>
        <a className="evidence-link" href="#evidence-title">자료와 계산 근거 다시 보기</a>
      </section>
    </>
  );
}
