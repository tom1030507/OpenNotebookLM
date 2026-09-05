import { test, expect } from '../support/fixtures.js';
import type { QueryResult } from '../support/api.js';
import { runtime } from '../support/runtime.js';
import { setupReadyUrlWorkspace, setupWorkspace } from '../support/ui.js';

test('answers from a ready source and persists messages and citation after reload', async ({
  api,
  page,
}, testInfo) => {
  const { project, documentId } = await setupReadyUrlWorkspace(
    api,
    page,
    testInfo,
    'cited-chat',
  );
  const question = 'What is the observatory access code?';

  await page.getByPlaceholder('Ask anything about your sources...').fill(question);
  const queryResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/query`
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Send message' }).click();
  const rawResponse = await queryResponse;
  expect(rawResponse.status()).toBe(200);
  const result = await rawResponse.json() as QueryResult;

  expect(result.model_used).toBe('fallback');
  expect(result.answer).toContain('ORBIT-7319');
  expect(result.sources.some((source) => (
    source.document_id === documentId
    && source.document_title === 'E2E Observatory Field Notes'
    && typeof source.text_preview === 'string'
    && source.text_preview.includes('ORBIT-7319')
  ))).toBe(true);

  const conversationId = result.conversation_id;
  expect(conversationId).not.toBeNull();
  if (!conversationId) {
    throw new Error('The successful query did not return a conversation id.');
  }

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  // The UI renders Markdown and compact citation controls; persisted text
  // retains the provider's labels and is checked separately below.
  const renderedAnswer = page.getByRole('main').locator('.prose').last();
  await expect(renderedAnswer).toContainText('ORBIT-7319');
  const citation = renderedAnswer.getByRole('button', { name: 'Preview source 1', exact: true });
  await expect(citation).toHaveText('[1]');
  await citation.hover();
  const preview = page.getByRole('tooltip');
  await expect(preview).toContainText('E2E Observatory Field Notes');
  await expect(preview).toContainText('ORBIT-7319');
  await page.keyboard.press('Escape');
  await expect(preview).toBeHidden();
  const sourcesPanel = page.getByText('Sources:', { exact: true }).last().locator('..');
  await expect(sourcesPanel).toContainText('E2E Observatory Field Notes');

  // The browser creates this shortened title before it issues /api/query.
  const conversationTitle = `${question.substring(0, 50)}...`;
  const listReloaded = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/conversations`
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await listReloaded).status()).toBe(200);

  const conversationItem = page
    .getByRole('region', { name: 'Conversations panel content' })
    .getByText(conversationTitle, { exact: true });
  await expect(conversationItem).toBeVisible();
  const detailReloaded = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/conversations/${conversationId}`
      && response.request().method() === 'GET',
  );
  await conversationItem.click();
  expect((await detailReloaded).status()).toBe(200);

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(renderedAnswer).toContainText('ORBIT-7319');
  await expect(citation).toHaveText('[1]');
  await citation.hover();
  await expect(preview).toContainText('ORBIT-7319');
  await page.keyboard.press('Escape');
  await expect(preview).toBeHidden();
  await expect(page.getByText('Sources:', { exact: true }).last().locator('..'))
    .toContainText('E2E Observatory Field Notes');

  const persisted = await api.conversation(conversationId);
  expect(persisted.messages.map((message) => message.role)).toEqual(['user', 'assistant']);
  const userMessage = persisted.messages.find((message) => message.role === 'user');
  const assistantMessage = persisted.messages.find((message) => message.role === 'assistant');
  expect(userMessage?.text).toBe(question);
  if (!assistantMessage) {
    throw new Error('The queried conversation did not persist an assistant message.');
  }
  expect(assistantMessage.text).toBe(result.answer);
  expect(assistantMessage.citations).toEqual(result.sources);
});

test('creates, renames, selects, and deletes conversations', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'conversation-crud');
  const fullTextNewButton = page
    .getByRole('button', { name: 'New Conversation' })
    .filter({ hasText: 'New Conversation' })
    .first();
  const createdResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/conversations`
      && response.request().method() === 'POST',
  );
  await fullTextNewButton.click();
  const created = await createdResponse;
  expect(created.status()).toBe(200);
  const first = await created.json() as { id: string };

  const panel = page.getByRole('region', { name: 'Conversations panel content' });
  const initialTitle = panel.getByText('New Conversation', { exact: true });
  await expect(initialTitle).toBeVisible();
  const initialActionContainer = initialTitle.locator('..').locator('..');
  await initialActionContainer.hover();
  await initialActionContainer.getByRole('button', { name: 'Rename conversation' }).click();
  const editingInput = panel.locator('input[type="text"]');
  const editingRow = editingInput.locator('..');
  const renamedResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/conversations/${first.id}`
      && response.request().method() === 'PUT',
  );
  await editingInput.fill('Renamed E2E Conversation');
  await editingRow.getByRole('button', { name: 'Save conversation name' }).click();
  expect((await renamedResponse).status()).toBe(200);
  await expect(panel.getByText('Renamed E2E Conversation', { exact: true })).toBeVisible();

  const secondResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/conversations`
      && response.request().method() === 'POST',
  );
  await fullTextNewButton.click();
  expect((await secondResponse).status()).toBe(200);

  const selectedResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/conversations/${first.id}`
      && response.request().method() === 'GET',
  );
  const renamedTitle = panel.getByText('Renamed E2E Conversation', { exact: true });
  await renamedTitle.click();
  const selected = await selectedResponse;
  expect(selected.status()).toBe(200);
  expect((await selected.json() as { title: string | null }).title).toBe('Renamed E2E Conversation');

  const renamedActionContainer = renamedTitle.locator('..').locator('..');
  page.once('dialog', async (confirmation) => {
    expect(confirmation.message()).toBe('Are you sure you want to delete this conversation?');
    await confirmation.accept();
  });
  const deletedResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/conversations/${first.id}`
      && response.request().method() === 'DELETE',
  );
  await renamedActionContainer.hover();
  await renamedActionContainer.getByRole('button', { name: 'Delete conversation' }).click();
  expect((await deletedResponse).status()).toBe(200);
  await expect(panel.getByText('Renamed E2E Conversation', { exact: true })).toHaveCount(0);
  expect((await api.listConversations(project.id)).map((conversation) => conversation.id))
    .not.toContain(first.id);
});
