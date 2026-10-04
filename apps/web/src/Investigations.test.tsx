import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import type { ApiGet, ApiPost } from './api';
import { EventWorkshop } from './EventWorkshop';
import { InvestigationView } from './InvestigationView';
import type { EventConditions, EventExecuteRequest, EventPlan, EventResult, InvestigationAnalysis } from './eventTypes';

const c: EventConditions = { tool: 'business_mix', entities: ['NAVER', '카카오'], company_codes: [], metrics: ['사업별 매출', '매출액', '영업이익'], start: '2021', end: '2025', frequency: '연간', comparison: '심층 비교', comparison_period: '조사 계획', statement_basis: '연결', amount_basis: '당기', age_range: '15-29세' };
const analysis: InvestigationAnalysis = { title: 'E · 성장 구조 변화', source_version: '공식 저장 원자료', focus_ids: ['F1'], method: ['같은 보고서 전기 비교'], tables: [{ title: 'NAVER · 사업 구성의 변화', columns: ['연도', '사업', '매출', '비중'], rows: [['2025', '커머스', '3688407', '30.65']], evidence_ids: ['F1'], note: '분류 변경을 확인하세요.' }] };
const catalog = { snapshots: [], entities: [], ages: [], notice: '', investigations: [{ tool: 'business_mix', title: 'E · 성장 구조 변화', question: 'NAVER와 카카오의 성장 구조가 어떻게 달라졌나?', source: 'OpenDART 사업보고서', steps: ['매출 비중과 증가액 비교'], calls: '공식 저장 원자료', archive_only: true, start: '2021', end: '2025' }] };
function setup() {
  const post = vi.fn(async (path: string, body: unknown) => {
    const req = body as EventExecuteRequest;
    if (path.endsWith('/plan')) return { request_id: 'p1', question: req.question, conditions: c, model: 'test', proposals: ['공식 저장 자료를 확인하세요.'], field_errors: {}, companies: [], trace: [], snapshot_id: null, status: 'ready', clarification: null } satisfies EventPlan;
    return { request_id: `result-${post.mock.calls.length}`, question: req.question, conditions: req.conditions, data_mode: req.mode, cache: null, analysis, facts: [{ id: 'F1', entity: 'NAVER', metric: '커머스 매출', period: '2025', value: '3688407', unit: '백만원', kind: 'observation', source_urls: ['https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260313001021'], retrieved_at: '2026-10-05T00:00:00Z', formula: '원자료 값', details: {} }], caveats: ['원문 확인'], coverage: 'complete', trace: [], brief: { status: 'complete', generation_method: 'gemini', model: 'test', content: { summary: { text: '자료로 확인한 구조 변화\n\n비교 가능한 범위를 살펴봅니다.', evidence_ids: ['F1'] }, findings: [{ text: '사업 구성의 차이', evidence_ids: ['F1'] }], limitations: ['인과관계를 단정하지 않습니다.'], follow_up_questions: ['분류 변경은 무엇인가?'] }, error: null, verification_status: 'review_required' }, generated_at: '2026-10-05T01:00:00Z', snapshot_id: null } satisfies EventResult;
  });
  render(<EventWorkshop part={2} get={vi.fn(async () => catalog) as ApiGet} post={post as ApiPost} />);
  return post;
}

test('prepared material is explicitly approved without an API parameter form', async () => {
  const post = setup();
  fireEvent.click(await screen.findByRole('button', { name: /E · 성장 구조 변화/ }));
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  await screen.findByRole('heading', { name: '제안한 조사 계획을 검토해 주세요' });
  expect(screen.queryByRole('textbox', { name: '시작 기간' })).toBeNull();
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.getByText(/최신 재조회가 아닙니다/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '이 계획으로 조사' }));
  await screen.findByText('사업 구성의 차이');
  expect(post.mock.calls[1][1]).toEqual({ question: catalog.investigations[0].question, conditions: c, approved: true, mode: 'archive' });
  expect(screen.getByRole('table', { name: 'NAVER · 사업 구성의 변화' })).toBeTruthy();
  expect(screen.getAllByText(/최신 재조회 아님/).length).toBeGreaterThan(0);
  expect(screen.getByText('자료로 확인한 구조 변화', { exact: false, selector: '.response-summary' }).className).toContain('preserve-lines');
});

test('natural-language revision hides the result and human review before replanning', async () => {
  setup();
  fireEvent.click(await screen.findByRole('button', { name: /E · 성장 구조 변화/ }));
  fireEvent.click(screen.getByRole('button', { name: '조사 계획 제안받기' }));
  fireEvent.click(await screen.findByRole('button', { name: '이 계획으로 조사' }));
  await screen.findByRole('heading', { name: '나의 취재 검토 기록' });
  fireEvent.change(screen.getByRole('textbox', { name: '사실 1 내용' }), { target: { value: '원문에서 확인한 사실' } });
  fireEvent.change(screen.getByRole('textbox', { name: '계획을 말로 수정하기' }), { target: { value: '최근 두 해만 보자' } });
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.queryByRole('heading', { name: '나의 취재 검토 기록' })).toBeNull();
  expect((screen.getByRole('button', { name: '이 계획으로 조사' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '수정 요청 반영' }));
  await waitFor(() => expect((screen.getByRole('button', { name: '이 계획으로 조사' }) as HTMLButtonElement).disabled).toBe(false));
});

test('analysis renders evidence links and plain text without trusting source markup', () => {
  const value = structuredClone(analysis); value.tables[0].rows[0][1] = '<script>bad()</script>';
  render(<InvestigationView analysis={value} />);
  const table = screen.getByRole('table');
  expect(within(table).getByText('<script>bad()</script>')).toBeTruthy();
  expect(table.querySelector('script')).toBeNull();
  expect(screen.getByRole('link', { name: '[F1]' }).getAttribute('href')).toBe('#event-F1');
});
