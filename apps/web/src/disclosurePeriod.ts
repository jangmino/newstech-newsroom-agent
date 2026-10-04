import type { DisclosurePeriodLimits } from './eventTypes';

// Fallback supports an older server or an unavailable catalog; the server revalidates approval.
export function disclosurePeriodLimits(): DisclosurePeriodLimits {
  return { max_days: 93, min_date: '2015-01-01', max_date: new Date().toISOString().slice(0, 10) };
}

function day(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value ? parsed : null;
}

export function disclosurePeriodError(startText: string, endText: string, limits: DisclosurePeriodLimits): string {
  const start = day(startText), end = day(endText);
  if (start === null || end === null) return '공시 시작일과 종료일을 YYYY-MM-DD 형식의 실제 날짜로 입력해 주세요.';
  if (start > end) return '공시 시작일은 종료일보다 늦을 수 없습니다. 두 날짜를 확인해 주세요.';
  if (startText < limits.min_date || endText > limits.max_date) return `공시 접수일은 ${limits.min_date}부터 ${limits.max_date}까지 선택해 주세요.`;
  const days = (end - start) / 86_400_000 + 1;
  if (days > limits.max_days) {
    const earliest = new Date(end - (limits.max_days - 1) * 86_400_000).toISOString().slice(0, 10);
    return `선택한 공시 기간은 시작일·종료일 포함 ${days}일입니다. 이 실습 앱은 한 번에 최대 ${limits.max_days}일을 조회합니다. 종료일을 유지하려면 시작일을 ${earliest} 이후로 바꾸거나, 기간을 나누어 각각 승인해 주세요.`;
  }
  return '';
}
