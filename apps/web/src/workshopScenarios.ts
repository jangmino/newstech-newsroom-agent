import type { QueryConditions } from "./types";

export const workshopQuestion = "최근 5년 동안 청년 고용이 가장 좋아진 지역은 어디인가?";
export type WorkshopScenarioId = "ambiguity" | "period" | "missing";

interface WorkshopScenario {
  id: WorkshopScenarioId;
  title: string;
  purpose: string;
  steps: string[];
  prepareLabel: string;
  conditions: QueryConditions;
  recovery?: { label: string; period: string; explanation: string };
}

const baseConditions: QueryConditions = {
  selected_source: "kosis", entity: "전국 시·도", metric: "고용률", period: "2020-2024",
  comparison: "증감 폭", filters: { age_range: "15-29세", frequency: "연간" },
};

export const workshopScenarios: WorkshopScenario[] = [
  {
    id: "ambiguity", title: "1. 모호한 질문", purpose: "‘최근’과 ‘좋아졌다’를 에이전트가 임의로 정하지 않는지 확인합니다.",
    steps: [
      "위의 ‘질문 분석’을 누르고 비어 있는 조건과 한국어 안내를 확인합니다.",
      "대상·지표·기간·비교 기준·연령을 직접 선택하거나 아래 예시 조건을 넣습니다.",
      "입력란을 확인한 뒤 ‘이 조건으로 조회’를 누릅니다. 조건 승인과 결과의 사실 검증은 별개입니다.",
    ],
    prepareLabel: "예시 조건 넣기", conditions: baseConditions,
  },
  {
    id: "period", title: "2. 지원 범위 밖 기간", purpose: "자료가 없는 기간은 임의로 대체하지 않고 조회를 멈추는지 확인합니다.",
    steps: [
      "위의 ‘질문 분석’을 누른 뒤 아래 버튼으로 지원하지 않는 기간을 넣습니다.",
      "2019-2024의 기간 안내를 읽고 ‘이 조건으로 조회’가 비활성화되는지 확인합니다.",
      "기간을 2020-2024로 수정하고 조건을 다시 확인한 뒤 직접 승인합니다.",
    ],
    prepareLabel: "지원하지 않는 기간 넣기", conditions: { ...baseConditions, period: "2019-2024" },
    recovery: {
      label: "기간을 2020-2024로 수정", period: "2020-2024",
      explanation: "가상 자료가 지원하는 기간으로 바꿉니다. 나머지 조건도 확인한 뒤 승인해 주세요.",
    },
  },
  {
    id: "missing", title: "3. 0 기준값과 누락값", purpose: "계산할 수 없는 값이 0이나 임의의 순위로 바뀌지 않는지 확인합니다.",
    steps: [
      "위의 ‘질문 분석’을 누르고 아래의 계산 불가 예시 조건을 넣습니다.",
      "직접 승인한 뒤 원자료 표에서 0 기준값·누락값의 차이와 계산 불가 이유를 읽습니다.",
      "기간을 2021-2023으로 바꾸고 재승인합니다. 비교 범위가 달라지므로 원래 취재 질문에 적합한지 판단하고 새 결과를 검토합니다.",
    ],
    prepareLabel: "계산 불가 예시 조건 넣기",
    conditions: { ...baseConditions, metric: "취업자 수", comparison: "증감률", filters: { age_range: "15-34세", frequency: "연간" } },
    recovery: {
      label: "기간을 2021-2023으로 수정", period: "2021-2023",
      explanation: "비교 기간 자체를 바꾸는 실습입니다. 원래 기간의 누락값을 해결한 것은 아니며, 취재 질문에 이 기간이 적합한지 다시 판단해야 합니다.",
    },
  },
];
