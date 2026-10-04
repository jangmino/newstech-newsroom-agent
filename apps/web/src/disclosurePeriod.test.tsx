import { expect, test } from 'vitest';
import { disclosurePeriodError } from './disclosurePeriod';
const limits = { max_days: 93, min_date: '2015-01-01', max_date: '2026-10-04' };

test.each([
  ['2025-01-01', '2025-04-03', ''],
  ['2025-01-01', '2025-04-04', '포함 94일'],
  ['2025-02-29', '2025-03-01', '실제 날짜'],
  ['2024-02-29', '2024-03-01', ''],
  ['2025-03-02', '2025-03-01', '늦을 수 없습니다'],
  ['2014-12-31', '2015-01-01', '2015-01-01부터'],
  ['2026-10-04', '2026-10-05', '2026-10-04까지'],
  ['2026-10-04', '2026-10-04', ''],
  ['', '2025-01-01', '실제 날짜'],
])('disclosure period %s to %s', (start, end, expected) => {
  const message = disclosurePeriodError(start, end, limits);
  if (expected) expect(message).toContain(expected); else expect(message).toBe('');
});
