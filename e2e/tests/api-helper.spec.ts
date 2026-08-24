import { test, expect } from '../support/fixtures.js';
import { accountFor } from '../support/ui.js';

test('creates isolated authenticated setup data through the real API', async ({ api }, testInfo) => {
  const account = accountFor(testInfo, 'api-contract');
  await api.register(account);
  await api.login(account);
  const project = await api.createProject('API Contract Project', 'Owned by this test');

  expect(project.name).toBe('API Contract Project');
  await expect.poll(async () => (await api.listProjects()).map((item) => item.id)).toContain(project.id);
});
