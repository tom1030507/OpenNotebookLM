import { createHash } from 'node:crypto';

import { expect, type Page, type TestInfo } from '@playwright/test';

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
  await expect(page).toHaveURL('/');
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
  await expect(page).toHaveURL('/');
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
