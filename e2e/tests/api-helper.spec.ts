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

test('models nullable titles and raw persisted conversation messages through the real API', async ({ api }, testInfo) => {
  const account = accountFor(testInfo, 'conversation-contract');
  await api.register(account);
  await api.login(account);
  const project = await api.createProject('Conversation Contract Project');
  const created = await api.createConversation(project.id, null);

  expect(created.title).toBeNull();
  await expect(api.conversation(created.id)).resolves.toMatchObject({
    id: created.id,
    project_id: project.id,
    title: null,
    messages: [],
  });

  const result = await api.query(project.id, created.id, 'What evidence is available?');
  expect(result.conversation_id).toBe(created.id);
  expect(Array.isArray(result.sources)).toBe(true);

  const detail = await api.conversation(created.id);
  expect(detail.title).toBeNull();
  expect(detail.messages.map((message) => message.role)).toEqual(['user', 'assistant']);
  for (const message of detail.messages) {
    expect(typeof message.role).toBe('string');
    expect(Array.isArray(message.citations)).toBe(true);
  }
});
