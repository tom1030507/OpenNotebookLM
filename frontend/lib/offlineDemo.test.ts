// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api, { ApiError } from './api';
import { clearSession, isOfflineDemoSession, OFFLINE_DEMO_TOKEN, storeSession } from './session';
import useStore from '@/store/useStore';

const user = { username: 'demo', email: 'demo@example.com' };

beforeEach(() => {
  window.localStorage.clear();
  clearSession();
  useStore.getState().resetForTests();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Backend unavailable')));
  storeSession(OFFLINE_DEMO_TOKEN, user, useStore.getState().clearAccountState);
});

afterEach(() => {
  clearSession();
  useStore.getState().resetForTests();
  vi.unstubAllGlobals();
});

describe('offline demo API boundary', () => {
  it('loads a linked sample workspace without any backend request', async () => {
    const [project] = await api.getProjects();
    const documents = await api.getDocuments(project.id);
    const [conversation] = await api.getConversations(project.id);
    const messages = await api.getMessages(conversation.id);
    const notes = await api.listNotes(project.id);

    expect(project.name).toContain('demo');
    expect(documents.length).toBeGreaterThan(0);
    expect(messages.some((message) => message.role === 'assistant')).toBe(true);
    expect(messages.flatMap((message) => message.citations ?? [])).toEqual(
      expect.arrayContaining([expect.objectContaining({ document_id: documents[0].id })]),
    );
    expect(notes[0].project_id).toBe(project.id);
    expect(await api.fetchDocumentContent(documents[0].id)).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('blocks writes, uploads, generation, text and blob transports locally', async () => {
    const [project] = await api.getProjects();
    const operations = [
      api.createProject({ name: 'New project' }),
      api.uploadDocument(project.id, new File(['source'], 'source.txt')),
      api.query({ project_id: project.id, query: 'A question' }),
      api.streamQuery({ project_id: project.id, query: 'A question' }),
      api.fetchProjectSummaryText(project.id),
      api.exportProject(project.id, 'markdown'),
    ];
    const results = await Promise.allSettled(operations);
    for (const result of results) {
      expect(result.status).toBe('rejected');
      if (result.status === 'rejected') {
        expect(result.reason.message).toMatch(/running backend/i);
      }
    }
    expect(isOfflineDemoSession()).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not resolve real or unknown resource IDs from demo fixtures', async () => {
    await expect(api.fetchDocumentContent('someone-elses-document')).rejects.toMatchObject({ status: 404 });
    await expect(api.getMessages('unknown-conversation')).rejects.toMatchObject({ status: 404 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('returns fresh copies of bundled data on reload', async () => {
    const [project] = await api.getProjects();
    project.name = 'Changed in memory';
    const [reloaded] = await api.getProjects();
    expect(reloaded.name).not.toBe(project.name);
    expect(isOfflineDemoSession()).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('clears cached workspace data when switching to a real account with the same username', () => {
    const clear = vi.fn();
    storeSession('real-backend-jwt', user, clear);
    expect(clear).toHaveBeenCalledOnce();
    expect(isOfflineDemoSession()).toBe(false);
  });

  it('clears real account data when entering the demo with the same username', () => {
    storeSession('real-backend-jwt', user);
    const clear = vi.fn();
    storeSession(OFFLINE_DEMO_TOKEN, user, clear);
    expect(clear).toHaveBeenCalledOnce();
  });

  it('uses the backend for a real token even when the username is demo', async () => {
    storeSession('real-backend-jwt', user);
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ projects: [], total: 0, page: 1, per_page: 100 })));
    expect(await api.getProjects()).toEqual([]);
    expect(fetch).toHaveBeenCalledOnce();
    expect(new Headers(vi.mocked(fetch).mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer real-backend-jwt');
  });

  it('ends offline mode on sign-out', () => {
    clearSession();
    expect(isOfflineDemoSession()).toBe(false);
  });

  it('preserves the demo session after a backend-required operation is refused', async () => {
    await expect(api.fetchProjectMindMap('offline-demo-project')).rejects.toBeInstanceOf(ApiError);
    expect(isOfflineDemoSession()).toBe(true);
  });
});
