import { test, expect } from '../support/fixtures.js';
import {
  accountFor,
  loginThroughUi,
  registerThroughUi,
  signOutThroughUi,
} from '../support/ui.js';

test('redirects an anonymous workspace visit to login', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL('/login');
  await expect(page.getByRole('button', { name: 'Login', exact: true })).toBeVisible();
});

test('registers and restores the signed-in session after reload', async ({ page }, testInfo) => {
  const account = accountFor(testInfo, 'register');
  await registerThroughUi(page, account);

  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
  const stored = await page.evaluate(() => ({
    access: localStorage.getItem('access_token'),
    auth: localStorage.getItem('auth_token'),
    user: localStorage.getItem('user'),
  }));
  expect(stored.access).toBeTruthy();
  expect(stored.auth).toBe(stored.access);
  expect(JSON.parse(stored.user ?? '{}')).toMatchObject({ username: account.username });

  await page.reload();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
});

test('rejects a wrong password without creating browser session state', async ({
  api,
  browserDiagnostics,
  page,
}, testInfo) => {
  const account = accountFor(testInfo, 'wrong-password');
  await api.register(account);
  await page.goto('/login');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill('incorrect-password');
  const rejected = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.status() === 401,
  );
  browserDiagnostics.allowExpectedAuthToken401();
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  await rejected;

  await expect(page.getByText('Incorrect username or password', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => [
    localStorage.getItem('access_token'),
    localStorage.getItem('auth_token'),
    localStorage.getItem('user'),
  ])).toEqual([null, null, null]);
  expect((await page.context().cookies()).find((cookie) => cookie.name === 'auth_token')).toBeUndefined();
});

test('signs out, clears the session, and protects browser back navigation', async ({ api, page }, testInfo) => {
  const account = accountFor(testInfo, 'logout');
  await api.register(account);
  await loginThroughUi(page, account);

  await signOutThroughUi(page);
  expect(await page.evaluate(() => [
    localStorage.getItem('access_token'),
    localStorage.getItem('auth_token'),
    localStorage.getItem('user'),
  ])).toEqual([null, null, null]);
  expect((await page.context().cookies()).find((cookie) => cookie.name === 'auth_token')).toBeUndefined();

  await page.goBack();
  await expect(page).toHaveURL('/login');
});
