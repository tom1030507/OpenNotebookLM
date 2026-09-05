import { readFile } from 'node:fs/promises';

import type { Page } from '@playwright/test';

import { test, expect } from '../support/fixtures.js';
import { runtime } from '../support/runtime.js';
import { setupReadyUrlWorkspace, setupWorkspace } from '../support/ui.js';

function observeExportRequest(page: Page, endpoint: string, method = 'GET'): () => void {
  const requests: Array<{ authorization: boolean; method: string; navigation: boolean; type: string }> = [];
  const responses: Array<{ authorization: boolean; status: number }> = [];
  page.on('request', (request) => {
    if (request.url() === endpoint) {
      requests.push({
        authorization: Boolean(request.headers().authorization),
        method: request.method(),
        navigation: request.isNavigationRequest(),
        type: request.resourceType(),
      });
    }
  });
  page.on('response', (response) => {
    if (response.url() === endpoint) {
      responses.push({
        authorization: Boolean(response.request().headers().authorization),
        status: response.status(),
      });
    }
  });
  return () => {
    expect(requests).toEqual([{
      authorization: true,
      method,
      navigation: false,
      type: 'fetch',
    }]);
    expect(responses).toEqual([{ authorization: true, status: 200 }]);
  };
}

test('renders a fallback mind map from ready source structure', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'mind-map');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/mindmap`
      && response.request().method() === 'POST',
  );
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Mind map', exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({
    project_id: project.id,
    project_name: project.name,
    model_used: 'fallback',
  });

  const dialog = page.getByRole('dialog', { name: `${project.name} mind map` });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    'From document structure',
  );
  await expect(dialog).toContainText('Observatory Operations');
  await dialog.getByRole('button', { name: 'Expand all branches' }).click();
  const previousZoom = await dialog.getByLabel('Zoom level').innerText();
  await dialog.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(dialog.getByLabel('Zoom level')).not.toHaveText(previousZoom);
  const zoomIn = dialog.getByRole('button', { name: 'Zoom in', exact: true });
  while (await zoomIn.isEnabled()) await zoomIn.click();
  const canvas = dialog.getByRole('region', { name: 'Mind map canvas' });
  const bounds = (await canvas.boundingBox())!;
  await page.mouse.move(bounds.x + 200, bounds.y + 10);
  await page.mouse.down();
  await page.mouse.move(bounds.x + 40, bounds.y + 10, { steps: 5 });
  await page.mouse.up();
  await expect.poll(() => canvas.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  await page.keyboard.down('Control');
  await page.mouse.wheel(0, 100);
  await page.keyboard.up('Control');
  await expect(dialog.getByLabel('Zoom level')).not.toHaveText('200%');
  await dialog.getByRole('button', { name: 'Fit to view' }).click();
  await dialog.getByRole('button', { name: 'Close mind map dialog', exact: true }).click();
  await expect(dialog).toBeHidden();
});

test('explores a mind map and brings a question back to mobile chat', async ({ api, page }, testInfo) => {
  const queryRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/query')) {
      queryRequests.push(request.url());
    }
  });
  await setupReadyUrlWorkspace(api, page, testInfo, 'mind-map-chat');
  const composer = page.getByRole('textbox', { name: 'Ask anything about your sources...' });
  await composer.fill('My existing question');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open Studio panel', exact: true }).click();
  await page.getByRole('complementary', { name: 'Studio' }).getByRole('button', { name: 'Mind map', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: /mind map$/ });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Expand all branches' }).click();
  await dialog.getByRole('button', { name: 'Enter full screen' }).click();
  await expect(dialog.getByRole('button', { name: 'Exit full screen' })).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Download mind map' })).toBeFocused();
  const concept = dialog.getByRole('button', { name: /^Explore / }).last();
  const label = (await concept.getAttribute('aria-label'))!.slice('Explore '.length);
  await concept.click();
  await dialog.getByRole('button', { name: 'Ask in chat' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('dialog', { name: 'Studio panel', exact: true })).toBeHidden();
  await expect(composer).toBeFocused();
  await expect(composer).toHaveValue(new RegExp(`^My existing question\\n\\nExplain`));
  expect(await composer.inputValue()).toContain(label);
  expect(queryRequests).toEqual([]);
});

test('downloads a Markdown project report', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'report');
  const endpoint = `${runtime.browserApiUrl}/export/project/${project.id}/summary`;
  const assertOneExportRequest = observeExportRequest(page, endpoint, 'POST');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === endpoint
      && response.request().method() === 'POST',
  );
  const downloadPromise = page.waitForEvent('download');
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Report', exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`${project.name} report.md`);
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  expect(await readFile(savedPath as string, 'utf8')).toContain(`# Project Summary: ${project.name}`);
  await expect(
    page.getByRole('complementary', { name: 'Studio' }).getByRole('button', { name: 'Report' }),
  ).toBeEnabled();
  assertOneExportRequest();
});

test('exports the current project as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'project-export');
  await page.getByRole('banner').getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export Project' });
  await dialog.getByRole('radio', { name: /markdown/i }).check();
  const endpoint = `${runtime.browserApiUrl}/export/project/${project.id}?format=markdown`;
  const assertOneExportRequest = observeExportRequest(page, endpoint);
  const responsePromise = page.waitForResponse(
    (response) => response.url() === endpoint
      && response.request().method() === 'GET',
  );
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export', exact: true }).click();
  expect((await responsePromise).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    `${project.name.replace(/[^a-z0-9]/gi, '_')}.markdown`,
  );
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  const markdown = await readFile(savedPath as string, 'utf8');
  expect(markdown).toContain(`# ${project.name}`);
  expect(markdown).toContain('## Documents');
  expect(markdown).toContain('### E2E Observatory Field Notes');
  expect(markdown).not.toContain(`# Project Summary: ${project.name}`);
  await expect(dialog.getByText('Exported!', { exact: true })).toBeVisible();
  assertOneExportRequest();
});

test('exports the selected conversation as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'conversation-export');
  const conversationTitle = 'Exportable Conversation';
  const conversation = await api.createConversation(project.id, conversationTitle);
  await api.query(project.id, conversation.id, 'What is the observatory access code?');
  const conversationsLoaded = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/conversations`
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await conversationsLoaded).status()).toBe(200);
  const detailLoaded = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/conversations/${conversation.id}`
      && response.request().method() === 'GET',
  );
  await page
    .getByRole('region', { name: 'Conversations panel content' })
    .getByText(conversationTitle, { exact: true })
    .click();
  expect((await detailLoaded).status()).toBe(200);

  await page.getByRole('banner').getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export Conversation' });
  await dialog.getByRole('radio', { name: /markdown/i }).check();
  const endpoint = `${runtime.browserApiUrl}/export/conversation/${conversation.id}?format=markdown`;
  const assertOneExportRequest = observeExportRequest(page, endpoint);
  const responsePromise = page.waitForResponse(
    (response) => response.url()
      === endpoint
      && response.request().method() === 'GET',
  );
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export', exact: true }).click();
  expect((await responsePromise).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('Exportable_Conversation.markdown');
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  const markdown = await readFile(savedPath as string, 'utf8');
  expect(markdown).toContain('What is the observatory access code?');
  expect(markdown).toContain('ORBIT-7319');
  await expect(dialog.getByText('Exported!', { exact: true })).toBeVisible();
  assertOneExportRequest();
});

test('renders the silent fallback video summary', async ({ api, page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
  });
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'video-summary');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/video-summary`
      && response.request().method() === 'POST',
  );
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Video summary', exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ model_used: 'fallback' });

  const dialog = page.getByRole('dialog', { name: `${project.name} video summary` });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Pause video summary', exact: true }).click();
  await expect(dialog).toContainText(
    'Narration taken from document structure rather than from a language model.',
  );
  await expect(dialog).toContainText(/Scene 1 of \d+/);
  await expect(dialog).toContainText(
    'This browser cannot read the narration out, so the slides play silently.',
  );
  await dialog.getByRole('button', { name: 'Close video summary dialog', exact: true }).click();
});

test('shows the unsupported audio fallback without host speech hardware', async ({ api, page }, testInfo) => {
  let summaryRequested = false;
  await page.addInitScript(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
  });
  page.on('request', (request) => {
    if (
      request.url().startsWith(`${runtime.browserApiUrl}/export/project/`)
      && request.url().endsWith('/summary')
      && request.method() === 'POST'
    ) {
      summaryRequested = true;
    }
  });
  await setupReadyUrlWorkspace(api, page, testInfo, 'audio-summary');
  const studio = page.getByRole('complementary', { name: 'Studio' });
  await expect(studio.getByRole('button', { name: 'Audio summary', exact: true })).toBeDisabled();
  await expect(studio.getByText('Not supported in this browser', { exact: true })).toBeVisible();
  expect(summaryRequested).toBe(false);
});

test('persists the dark theme across reload', async ({ api, page }, testInfo) => {
  await setupWorkspace(api, page, testInfo, 'dark-theme');
  await page.getByRole('banner').getByRole('button', { name: 'Settings', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Settings' });
  await dialog.getByRole('button', { name: 'Dark', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Dark', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await dialog.getByRole('button', { name: 'Save Changes', exact: true }).click();

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => localStorage.getItem('open-notebook-theme'))).toBe('dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => localStorage.getItem('open-notebook-theme'))).toBe('dark');
});
