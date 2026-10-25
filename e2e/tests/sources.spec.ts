import { test, expect } from '../support/fixtures.js';
import { generatePdf } from '../support/pdf.js';
import {
  openAddSourceDialog,
  setupReadyUrlWorkspace,
  setupWorkspace,
  sourceRow,
} from '../support/ui.js';

test('uploads, indexes, previews, and removes a PDF source', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'pdf-source');
  const filename = 'observatory-field-notes.pdf';
  const filePath = testInfo.outputPath(filename);
  await generatePdf(filePath, 'Observatory Field Notes', 'The observatory access code is ORBIT-7319.');

  const dialog = await openAddSourceDialog(page);
  await dialog.locator('input[type="file"]').setInputFiles(filePath);
  const uploadResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Upload 1 file(s)', exact: true }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(200);
  const { doc_id: documentId } = await uploaded.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const row = sourceRow(page, filename);
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });

  await row.hover();
  const protectedFile = page.waitForResponse(
    (response) => response.url().endsWith(`/api/docs/${documentId}/file`) && response.status() === 200,
  );
  await row.getByRole('button', { name: 'Preview document' }).click();
  await protectedFile;
  const preview = page.getByRole('dialog', { name: filename });
  await expect(preview.locator(`iframe[title="${filename}"]`)).toHaveAttribute('src', /^blob:/);
  await preview.getByRole('button', { name: 'Close document preview dialog' }).click();

  page.once('dialog', async (confirmation) => {
    expect(confirmation.message()).toBe('Are you sure you want to delete this document?');
    await confirmation.accept();
  });
  const removed = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents/${documentId}`)
      && response.request().method() === 'DELETE',
  );
  await row.hover();
  await row.getByRole('button', { name: 'Remove source' }).click();
  expect((await removed).status()).toBe(200);
  await expect(sourceRow(page, filename)).toHaveCount(0);
  expect((await api.listProjectDocuments(project.id)).map((document) => document.id)).not.toContain(documentId);
});

test('imports, searches, and removes a controlled URL source', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'url-source');
  const dialog = await openAddSourceDialog(page);
  await dialog.getByRole('button', { name: 'URL', exact: true }).click();
  await dialog.getByPlaceholder('Enter website URL...').fill('https://e2e.invalid/observatory');
  const importResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload-url`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Add', exact: true }).click();
  const imported = await importResponse;
  expect(imported.status()).toBe(200);
  const { doc_id: documentId } = await imported.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const title = 'E2E Observatory Field Notes';
  const row = sourceRow(page, title);
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByLabel('Search sources').fill('Observatory');
  await expect(row).toBeVisible();
  await page.getByLabel('Search sources').fill('missing-source');
  await expect(row).toHaveCount(0);
  await page.getByLabel('Search sources').clear();

  const visibleRow = sourceRow(page, title);
  page.once('dialog', (confirmation) => confirmation.accept());
  const removed = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents/${documentId}`)
      && response.request().method() === 'DELETE',
  );
  await visibleRow.hover();
  await visibleRow.getByRole('button', { name: 'Remove source' }).click();
  expect((await removed).status()).toBe(200);
  await expect(sourceRow(page, title)).toHaveCount(0);
});

test('previews the indexed text for a controlled URL source', async ({ api, page }, testInfo) => {
  const { documentId } = await setupReadyUrlWorkspace(api, page, testInfo, 'url-preview');
  const title = 'E2E Observatory Field Notes';
  const row = sourceRow(page, title);
  const contentResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/docs/${documentId}/content`)
      && response.request().method() === 'GET',
  );

  await row.hover();
  await row.getByRole('button', { name: 'Preview document' }).click();
  expect((await contentResponse).status()).toBe(200);
  const preview = page.getByRole('dialog', { name: title });
  await expect(preview).toContainText('The observatory access code is ORBIT-7319.');
  await expect(
    preview.getByRole('link', { name: 'https://e2e.invalid/observatory' }),
  ).toHaveAttribute('href', 'https://e2e.invalid/observatory');
  await expect(preview.locator('iframe')).toHaveCount(0);
  await preview.getByRole('button', { name: 'Close document preview dialog' }).click();
});

test('drafts a source-guide topic question with only that source selected', async ({ api, page }, testInfo) => {
  const { project, documentId } = await setupReadyUrlWorkspace(api, page, testInfo, 'source-guide');
  const otherDocumentId = await api.uploadText(
    project.id,
    'Secondary observatory notes',
    'These notes are unrelated to the source being previewed.',
  );
  await api.waitForDocumentReady(otherDocumentId);
  const documents = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await documents).status()).toBe(200);

  const row = sourceRow(page, 'E2E Observatory Field Notes');
  const guideResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/docs/${documentId}/guide`)
      && response.request().method() === 'GET',
  );
  await row.hover();
  await row.getByRole('button', { name: 'Preview document' }).click();
  const preview = page.getByRole('dialog', { name: 'E2E Observatory Field Notes' });
  const guide = await (await guideResponse).json() as { summary: string; topics: string[] };
  const topic = guide.topics[0];
  await expect(preview.getByLabel('Source guide')).toContainText(guide.summary);

  const queryRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/query')) {
      queryRequests.push(request.url());
    }
  });
  await preview.getByRole('button', { name: topic, exact: true }).click();
  await expect(preview).toBeHidden();
  const composer = page.getByRole('textbox', { name: 'Ask anything about your sources...' });
  await expect(composer).toHaveValue(`What does this source say about ${topic}?`);
  expect(queryRequests).toEqual([]);

  const queryRequest = page.waitForRequest(
    (request) => request.method() === 'POST'
      && new URL(request.url()).pathname.endsWith('/query'),
  );
  await composer.press('Enter');
  expect((await queryRequest).postDataJSON().document_ids).toEqual([documentId]);
});

test('imports a controlled YouTube transcript and reaches ready', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'youtube-source');
  const dialog = await openAddSourceDialog(page);
  await dialog.getByRole('button', { name: 'YouTube', exact: true }).click();
  await dialog.getByPlaceholder('Enter YouTube URL...').fill(
    'https://www.youtube.com/watch?v=e2eOrbit7319',
  );
  const importResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload-youtube`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Add', exact: true }).click();
  const imported = await importResponse;
  expect(imported.status()).toBe(200);
  const { doc_id: documentId } = await imported.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const row = sourceRow(page, 'YouTube: e2eOrbit7319');
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });
  const persisted = (await api.listProjectDocuments(project.id)).find(
    (document) => document.id === documentId,
  );
  expect(persisted).toMatchObject({
    source_type: 'youtube',
    title: 'YouTube: e2eOrbit7319',
    status: 'ready',
  });
});
