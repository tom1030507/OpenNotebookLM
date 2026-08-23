import { test, expect } from '../support/fixtures.js';
import { runtime } from '../support/runtime.js';

test('serves the isolated backend and protects the workspace', async ({ page, request }) => {
  const health = await request.get('http://127.0.0.1:8100/healthz');

  expect(health.ok()).toBe(true);
  expect(await health.json()).toMatchObject({
    ok: true,
    database: 'healthy',
    environment: 'test',
    config: { llm_mode: 'none', debug: false },
  });

  await page.goto('/');
  await expect(page).toHaveURL(`${runtime.frontendUrl}/login`);
  await expect(page.getByRole('button', { name: 'Login' })).toBeVisible();
});
