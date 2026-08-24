import { test, expect } from '../support/fixtures.js';
import {
  accountFor,
  createProjectThroughUi,
  loginThroughUi,
  signOutThroughUi,
} from '../support/ui.js';

test('creates, selects, and reloads a project from the backend', async ({ api, page }, testInfo) => {
  const account = accountFor(testInfo, 'project-persistence');
  await api.register(account);
  await api.login(account);
  await loginThroughUi(page, account);
  const name = `E2E Project ${testInfo.retry}`;
  const created = await createProjectThroughUi(page, name, 'Persistence coverage');

  await expect(page.getByRole('combobox', { name: 'Select a project' })).toHaveValue(created.id);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();

  const projectsLoaded = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await projectsLoaded).status()).toBe(200);
  await expect(page.getByRole('combobox', { name: 'Select a project' })).toHaveValue(created.id);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  expect((await api.listProjects()).map((project) => project.id)).toContain(created.id);
});

test('never exposes another account project or source', async ({ api, page }, testInfo) => {
  const accountA = accountFor(testInfo, 'owner-a');
  const accountB = accountFor(testInfo, 'owner-b');
  await api.register(accountA);
  await api.login(accountA);
  const projectA = await api.createProject('Account A Observatory', 'Private A data');
  const documentA = await api.uploadUrl(projectA.id, 'https://e2e.invalid/observatory');
  await api.waitForDocumentReady(documentA);

  await api.register(accountB);
  await api.login(accountB);
  const projectB = await api.createProject('Account B Notebook', 'Private B data');

  await loginThroughUi(page, accountA);
  await expect(page.getByRole('heading', { name: projectA.name, exact: true })).toBeVisible();
  await expect(page.getByText('E2E Observatory Field Notes', { exact: true })).toBeVisible();
  await signOutThroughUi(page);
  await page.reload();

  const projectsLoaded = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'GET',
  );
  await loginThroughUi(page, accountB);
  expect((await projectsLoaded).status()).toBe(200);
  await expect(page.getByRole('heading', { name: projectB.name, exact: true })).toBeVisible();
  await expect(page.getByText(projectA.name, { exact: true })).toHaveCount(0);
  await expect(page.getByText('E2E Observatory Field Notes', { exact: true })).toHaveCount(0);

  const forbidden = await api.projectDocumentsResponse(projectA.id);
  expect(forbidden.status()).toBe(404);
});
