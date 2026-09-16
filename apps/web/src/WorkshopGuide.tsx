import { conditionErrors } from "./conditions";
import type { ExecutionResponse, PlanResponse, QueryConditions } from "./types";
import { workshopScenarios, type WorkshopScenarioId } from "./workshopScenarios";

export function WorkshopGuide({ selected, plan, draft, result, busy, error, onStart, onClose, onApply }: {
  selected: WorkshopScenarioId | null;
  plan: PlanResponse | null;
  draft: QueryConditions | null;
  result: ExecutionResponse | null;
  busy: "plan" | "execute" | null;
  error: string | null;
  onStart: (id: WorkshopScenarioId) => void;
  onClose: () => void;
  onApply: (conditions: QueryConditions) => void;
}) {
  const scenario = workshopScenarios.find((item) => item.id === selected);
  const recovery = scenario?.recovery;
  const ready = plan?.query_plan.selected_source === "kosis" && draft?.selected_source === "kosis";
  const unavailable = result?.calculation?.rows.some((row) => row.status !== "calculated") ?? false;
  const errors = plan && draft ? conditionErrors(plan, draft) : [];
  const canRecover = ready && scenario?.recovery && (selected === "period"
    ? draft.period.trim() === scenario.conditions.period : unavailable);
  let guidance = "위의 ‘질문 분석’을 눌러 실습을 시작해 주세요.";
  if (busy) guidance = busy === "plan" ? "질문을 해석하고 있습니다. 잠시 기다려 주세요." : "승인한 조건의 모의 결과를 준비하고 있습니다.";
  else if (error) guidance = plan
    ? "요청이 완료되지 않았습니다. 오류 안내와 입력한 조건을 확인하고 ‘이 조건으로 조회’를 다시 눌러 주세요."
    : "질문 분석을 완료하지 못했습니다. 오류 안내를 확인하고 ‘질문 분석’을 다시 눌러 주세요.";
  else if (result) guidance = unavailable
    ? "계산 불가 결과가 있습니다. 아래 원자료 표의 이유와 경고를 읽고, 비교 기간을 바꿀지 판단해 주세요."
    : "이번 결과에는 계산 불가 값이 없습니다. 승인 조건·근거·해석 한계를 읽고 실습 검토를 진행해 주세요.";
  else if (plan && !ready) guidance = "청년 고용 예시 질문을 다시 분석해 주세요.";
  else if (ready) guidance = errors.length
    ? "아래 조건 입력란에 확인이 필요한 항목이 있습니다. 안내를 읽고 조건을 수정해 주세요."
    : "입력한 조건을 확인한 뒤 아래의 ‘이 조건으로 조회’를 눌러 주세요. 예시 조건을 넣는 것만으로는 조회하지 않습니다.";

  return (
    <section className="card workshop-guide" aria-labelledby="workshop-guide-title">
      <p className="step">짧은 실습 · mock</p>
      <h2 id="workshop-guide-title">막히는 상황 체험</h2>
      <p className="field-help">장면을 선택하면 기존 청년 고용 예시 질문으로 시작합니다. 현재 결과·비교·검토 표시는 초기화됩니다.</p>
      <div className="guide-options" aria-label="체험할 장면">
        {workshopScenarios.map((item) => (
          <button type="button" key={item.id} aria-pressed={selected === item.id} onClick={() => onStart(item.id)}>{item.title}</button>
        ))}
      </div>
      {scenario && (
        <div className="guide-active">
          <h3>{scenario.title}</h3>
          <p>{scenario.purpose}</p>
          <ol>{scenario.steps.map((step) => <li key={step}>{step}</li>)}</ol>
          <p className="guide-status" role="status" aria-live="polite" aria-atomic="true">{guidance}</p>
          <p className="field-help"><strong>적용할 예시 조건: </strong>{scenario.conditions.entity} · {scenario.conditions.metric} · {scenario.conditions.period} · {scenario.conditions.comparison} · {scenario.conditions.filters.age_range} · 연간</p>
          <div className="guide-actions">
            <button type="button" className="secondary" disabled={!ready || busy !== null} onClick={() => onApply(scenario.conditions)}>{scenario.prepareLabel}</button>
            {ready && <a className="evidence-link" href="#conditions-title">조건 입력란 보기</a>}
          </div>
          {canRecover && recovery && draft && (
            <div className="guide-recovery">
              <p>{recovery.explanation}</p>
              <button type="button" className="secondary" disabled={busy !== null}
                onClick={() => onApply({ ...draft, period: recovery.period })}>{recovery.label}</button>
            </div>
          )}
          {result && <a className="evidence-link" href="#evidence-title">승인된 자료와 계산 근거 보기</a>}
          <p className="field-help">예시는 참가자가 선택하는 실습 조건입니다. 공식 통계나 사실 검증 완료를 뜻하지 않습니다. 자유롭게 조건을 수정할 수 있습니다.</p>
          <button type="button" className="guide-close" onClick={onClose}>안내 닫기</button>
        </div>
      )}
    </section>
  );
}
