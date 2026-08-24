import { readFile } from 'node:fs/promises';

import { test, expect } from '../support/fixtures.js';
import { runtime } from '../support/runtime.js';
import { setupReadyUrlWorkspace, setupWorkspace } from '../support/ui.js';

test('renders a fallback mind map from ready source structure', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'mind-map');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/projects/${project.id}/mindmap`
      && response.request().method() === 'GET',
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
    'Topics taken from document structure rather than from a language model.',
  );
  await expect(dialog).toContainText('Observatory Operations');
  await dialog.getByRole('button', { name: 'Close mind map dialog', exact: true }).click();
});

test('downloads a Markdown project report', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'report');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/export/project/${project.id}/summary`
      && response.request().method() === 'GET',
  );
  const downloadPromise = page.waitForEvent('download');
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Report', exact: true })
    .click();
  expect((await responsePromise).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`${project.name} report.md`);
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  expect(await readFile(savedPath as string, 'utf8')).toContain(`# Project Summary: ${project.name}`);
});

test('exports the current project as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'project-export');
  await page.getByRole('banner').getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export Project' });
  await dialog.getByRole('radio', { name: /markdown/i }).check();
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/export/project/${project.id}?format=markdown`
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
  expect(await readFile(savedPath as string, 'utf8')).toContain(project.name);
});

test('exports the selected conversation as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'conversation-export');
  const conversationTitle = 'Exportable Conversation';
  const conversation = await api.createConversation(project.id, conversationTitle);
  await api.query(project.id, conversation.id, 'What is the observatory access code?');
  const conversationsLoaded = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/projects/${project.id}/conversations`
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await conversationsLoaded).status()).toBe(200);
  const detailLoaded = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/conversations/${conversation.id}`
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
  const responsePromise = page.waitForResponse(
    (response) => response.url()
      === `${runtime.apiUrl}/export/conversation/${conversation.id}?format=markdown`
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
});

test('renders the silent fallback video summary', async ({ api, page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
  });
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'video-summary');
  const responsePromise = page.waitForResponse(
    (response) => response.url() === `${runtime.apiUrl}/projects/${project.id}/video-summary`
      && response.request().method() === 'GET',
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
      request.url().startsWith(`${runtime.apiUrl}/export/project/`)
      && request.url().endsWith('/summary')
      && request.method() === 'GET'
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
