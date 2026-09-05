import { execFileSync } from 'node:child_process';
import path from 'node:path';

import { test, expect } from '../support/fixtures.js';
import type { JsonObject, JsonValue, QueryResult } from '../support/api.js';
import { generatePdf } from '../support/pdf.js';
import { runtime } from '../support/runtime.js';
import { openAddSourceDialog, setupWorkspace, sourceRow } from '../support/ui.js';

const IDENTIFIER = 'ORBIT-FULL-7319';
const MODEL_NAME = 'intfloat/multilingual-e5-base';
const FAST_MODEL_NAME = 'e2e-token-hash-v1';

function asObject(value: JsonValue): JsonObject | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

function sourceMatchesDocument(
  source: JsonObject,
  documentId: string,
  filename: string,
): boolean {
  return source.document_id === documentId
    && source.document_title === filename
    && source.page_num === 1
    && typeof source.text_preview === 'string'
    && source.text_preview.includes(IDENTIFIER);
}

function citationsContainDocument(
  citations: JsonValue,
  documentId: string,
  filename: string,
): boolean {
  return Array.isArray(citations) && citations.some((citation) => {
    const source = asObject(citation);
    return source !== undefined && sourceMatchesDocument(source, documentId, filename);
  });
}

function inspectStoredEmbeddings(documentId: string): Array<{ model_name: string; vector_json: unknown }> {
  const python = process.env.E2E_PYTHON ?? 'python';
  const database = path.join(runtime.root, 'opennotebook.db');
  const script = [
    'import json, sqlite3, sys',
    'connection = sqlite3.connect(sys.argv[1])',
    'rows = connection.execute(',
    "  'SELECT embeddings.model_name, embeddings.vector_json FROM embeddings '",
    "  'JOIN chunks ON chunks.id = embeddings.chunk_id WHERE chunks.document_id = ?',",
    '  (sys.argv[2],),',
    ').fetchall()',
    "print(json.dumps([{'model_name': row[0], 'vector_json': json.loads(row[1])} for row in rows]))",
  ].join('\n');
  const output = execFileSync(python, ['-c', script, database, documentId], {
    encoding: 'utf8',
    windowsHide: true,
  });
  return JSON.parse(output) as Array<{ model_name: string; vector_json: unknown }>;
}

test('indexes and retrieves a generated PDF with production embeddings', async ({ api, page }, testInfo) => {
  test.setTimeout(10 * 60_000);
  expect(process.env.FULL_RAG_E2E).toBe('1');
  expect(testInfo.project.name).toBe('chromium-full-rag');

  const { project } = await setupWorkspace(api, page, testInfo, 'full-rag');
  const filename = 'full-rag-observatory.pdf';
  const filePath = testInfo.outputPath(filename);
  await generatePdf(
    filePath,
    'Full RAG Observatory Manual',
    `The emergency observatory access identifier is ${IDENTIFIER}.`,
  );

  const dialog = await openAddSourceDialog(page);
  await dialog.locator('input[type="file"]').setInputFiles(filePath);
  const uploadResponse = page.waitForResponse(
    (response) => response.url() === `${runtime.browserApiUrl}/projects/${project.id}/upload`
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Upload 1 file(s)', exact: true }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(200);
  const { doc_id: documentId } = await uploaded.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId, 8 * 60_000);
  await expect(sourceRow(page, filename).getByText('Ready', { exact: true }))
    .toBeVisible({ timeout: 15_000 });
  const persistedDocument = (await api.listProjectDocuments(project.id)).find(
    (document) => document.id === documentId,
  );
  expect(persistedDocument).toMatchObject({
    id: documentId,
    title: filename,
    status: 'ready',
  });
  expect(persistedDocument?.chunk_count).toBeGreaterThan(0);

  const question = 'What is the emergency observatory access identifier?';
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
  expect(result.conversation_id).not.toBeNull();
  expect(result.chunks_used).toBeGreaterThanOrEqual(1);
  expect(result.answer).toContain(IDENTIFIER);
  expect(result.sources.some((source) => sourceMatchesDocument(source, documentId, filename))).toBe(true);

  const conversationId = result.conversation_id;
  if (!conversationId) {
    throw new Error('The successful query did not return a conversation id.');
  }

  const embeddings = inspectStoredEmbeddings(documentId);
  expect(embeddings).not.toHaveLength(0);
  for (const embedding of embeddings) {
    expect(embedding.model_name).toBe(MODEL_NAME);
    expect(embedding.model_name).not.toBe(FAST_MODEL_NAME);
    expect(Array.isArray(embedding.vector_json)).toBe(true);
    expect(embedding.vector_json).toHaveLength(768);
  }

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  const renderedAnswer = page.getByRole('main').locator('.prose').last();
  await expect(renderedAnswer).toContainText(IDENTIFIER);
  const citation = renderedAnswer.getByRole('button', { name: 'Preview source 1', exact: true });
  await expect(citation).toHaveText('[1]');
  await citation.hover();
  const preview = page.getByRole('tooltip');
  await expect(preview).toContainText(filename);
  await expect(preview).toContainText('Page 1');
  await page.keyboard.press('Escape');
  await expect(preview).toBeHidden();
  const sourcesPanel = page.getByText('Sources:', { exact: true }).last().locator('..');
  await expect(sourcesPanel).toContainText(filename);
  await expect(sourcesPanel).toContainText('page 1');

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
  await expect(renderedAnswer).toContainText(IDENTIFIER);
  await expect(citation).toHaveText('[1]');
  await citation.hover();
  await expect(preview).toContainText(filename);
  await page.keyboard.press('Escape');
  await expect(preview).toBeHidden();
  const reloadedAssistant = page.getByText('Sources:', { exact: true }).last().locator('..');
  await expect(reloadedAssistant).toContainText(filename);
  await expect(reloadedAssistant).toContainText('page 1');

  const persisted = await api.conversation(conversationId);
  expect(persisted.messages.map((message) => message.role)).toEqual(['user', 'assistant']);
  const userMessage = persisted.messages.find((message) => message.role === 'user');
  const assistantMessage = persisted.messages.find((message) => message.role === 'assistant');
  expect(userMessage?.text).toBe(question);
  if (!assistantMessage) {
    throw new Error('The queried conversation did not persist an assistant message.');
  }
  expect(assistantMessage.text).toBe(result.answer);
  expect(citationsContainDocument(assistantMessage.citations, documentId, filename)).toBe(true);
});
