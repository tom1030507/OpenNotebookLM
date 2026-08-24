import { createHash } from 'node:crypto';

import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';

import type { E2EApi, Project } from './api.js';

// A clean Next dev run can cold-compile `/` longer than the global 10s expect
// timeout immediately after authentication; this is not a retry or a sleep.
const POST_AUTH_NAVIGATION_TIMEOUT_MS = 30_000;

export interface Account {
  username: string;
  email: string;
  password: string;
}

export function accountFor(testInfo: TestInfo, suffix: string): Account {
  const digest = createHash('sha256')
    .update([
      process.env.E2E_RUN_ID,
      testInfo.project.name,
      testInfo.file,
      testInfo.title,
      testInfo.retry,
      suffix,
    ].join('|'))
    .digest('hex')
    .slice(0, 18);
  return {
    username: `e2e_${digest}`,
    email: `e2e_${digest}@example.test`,
    password: 'E2E-pass-7319!',
  };
}

export async function loginThroughUi(page: Page, account: Account): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  const tokenResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  expect((await tokenResponse).status()).toBe(200);
  await expect(page).toHaveURL('/', { timeout: POST_AUTH_NAVIGATION_TIMEOUT_MS });
  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
}

export async function registerThroughUi(page: Page, account: Account): Promise<void> {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Email').fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByLabel('Confirm Password').fill(account.password);
  const registration = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/register') && response.request().method() === 'POST',
  );
  const tokenResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  expect((await registration).status()).toBe(200);
  expect((await tokenResponse).status()).toBe(200);
  await expect(page).toHaveURL('/', { timeout: POST_AUTH_NAVIGATION_TIMEOUT_MS });
}

export async function createProjectThroughUi(
  page: Page,
  name: string,
  description: string,
): Promise<{ id: string; name: string }> {
  await page.getByRole('banner').getByRole('button', { name: 'New Project', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Create New Project' });
  await dialog.getByLabel('Project Name').fill(name);
  await dialog.getByLabel('Project Description').fill(description);
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Create Project', exact: true }).click();
  const result = await created;
  expect(result.status()).toBe(200);
  return result.json() as Promise<{ id: string; name: string }>;
}

export async function signOutThroughUi(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL('/login');
}

export async function openAddSourceDialog(page: Page) {
  const sources = page.getByRole('complementary', { name: 'Sources' });
  await sources.getByRole('button', { name: 'Add Source', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Add Source' });
  await expect(dialog).toBeVisible();
  return dialog;
}

export async function setupWorkspace(
  api: E2EApi,
  page: Page,
  testInfo: TestInfo,
  suffix: string,
): Promise<{ account: Account; project: Project }> {
  const account = accountFor(testInfo, suffix);
  await api.register(account);
  await api.login(account);
  const project = await api.createProject(`E2E ${suffix} ${testInfo.retry}`, 'Browser workflow');
  await loginThroughUi(page, account);
  await expect(page.getByRole('heading', { name: project.name, exact: true })).toBeVisible();
  return { account, project };
}

export function sourceRow(page: Page, title: string): Locator {
  const sources = page.getByRole('complementary', { name: 'Sources' });
  return sources
    .getByText(title, { exact: true })
    .locator('..')
    .locator('..')
    .locator('..');
}

export async function setupReadyUrlWorkspace(
  api: E2EApi,
  page: Page,
  testInfo: TestInfo,
  suffix: string,
): Promise<{ account: Account; project: Project; documentId: string }> {
  const { account, project } = await setupWorkspace(api, page, testInfo, suffix);
  const documentId = await api.uploadUrl(project.id, 'https://e2e.invalid/observatory');
  await api.waitForDocumentReady(documentId);
  const documentsLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await documentsLoaded).status()).toBe(200);
  await expect(sourceRow(page, 'E2E Observatory Field Notes').getByText('Ready', { exact: true }))
    .toBeVisible({ timeout: 10_000 });
  return { account, project, documentId };
}
