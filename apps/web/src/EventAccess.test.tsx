import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { WorkshopAccess } from './WorkshopAccess';
const code = 'synthetic-event-access-code';
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });

test('event catalog is protected and entering never calls Gemini or public data', async () => {
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async (path, init) => {
    if (path === '/api/v1/access') return json({ required: true, available: true });
    expect(path).toBe('/api/v1/event/catalog');
    expect(new Headers(init?.headers).get('X-Workshop-Code')).toBe(code);
    expect(init?.body).toBeUndefined();
    return json({ snapshots: [], entities: [], ages: [], notice: '' });
  });
  render(<WorkshopAccess />);
  fireEvent.change(await screen.findByLabelText('행사 접근코드'), { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: '실습 입장' }));
  await screen.findByRole('button', { name: '조사 계획 제안받기' });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(fetch.mock.calls.every(([path]) => String(path).endsWith('/access') || String(path).endsWith('/catalog'))).toBe(true);
  expect(document.body.textContent).not.toContain(code);
});

test('event catalog access rejection returns to entry without exposing prior UI', async () => {
  vi.mocked(globalThis.fetch).mockImplementation(async path => path === '/api/v1/access' ? json({ required: true, available: true }) : json({ detail: { code: 'workshop_access_required', message: '입장 필요', field_errors: {} } }, 401));
  render(<WorkshopAccess />);
  fireEvent.change(await screen.findByLabelText('행사 접근코드'), { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: '실습 입장' }));
  await screen.findByText(/행사 접근코드를 다시 확인/);
  expect(screen.queryByRole('button', { name: '조사 계획 제안받기' })).toBeNull();
});
