import { test, expect } from '../support/fixtures.js';
import { runtime } from '../support/runtime.js';

test('serves the isolated backend and protects the workspace', async ({ page, request }) => {
  const health = await request.get('http://127.0.0.1:8100/healthz');

  expect(health.ok()).toBe(true);
  expect(await health.json()).toMatchObject({
    ok: true,
    database: 'unchecked; use /readyz',
    environment: 'test',
    config: { llm_mode: 'none', debug: false },
  });

  const readiness = await request.get('http://127.0.0.1:8100/readyz');
  expect(readiness.ok()).toBe(true);
  expect(await readiness.json()).toEqual({ ok: true });

  await page.goto('/');
  await expect(page).toHaveURL(`${runtime.frontendUrl}/login`);
  await expect(page.getByRole('button', { name: 'Login' })).toBeVisible();

  const browserHealth = await page.evaluate(async () => {
    const response = await fetch('http://127.0.0.1:8100/healthz');
    return {
      body: await response.json(),
      ok: response.ok,
      status: response.status,
    };
  });
  expect(browserHealth).toMatchObject({
    ok: true,
    status: 200,
    body: { ok: true, environment: 'test' },
  });
});
