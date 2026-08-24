// @vitest-environment jsdom

/**
 * The API refuses anonymous callers, so every request the client makes has to
 * carry the signed-in token — not just the one endpoint that asks for an
 * account. These tests pin that, and pin what happens when the backend rejects
 * the token anyway: the workspace gives up the session instead of leaving the
 * user on a screen where every panel fails on its own.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api from './api';
import { AUTH_TOKEN_COOKIE, clearSession, storeSession } from './session';
import useStore from '@/store/useStore';


const jsonResponse = (body: unknown, status = 200) => new Response(
  JSON.stringify(body),
  { status, headers: { 'Content-Type': 'application/json' } },
);

const emptyProjectList = () => jsonResponse({
  projects: [],
  total: 0,
  page: 1,
  per_page: 10,
});

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });

  return { promise, resolve };
};

const seedWorkspace = (account: 'a' | 'b') => {
  const project = {
    id: `project-${account}`,
    name: `Account ${account.toUpperCase()} project`,
    description: null,
    meta_json: {},
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    document_count: 1,
    conversation_count: 1,
  };
  const conversation = {
    id: `conversation-${account}`,
    project_id: project.id,
    title: `Account ${account.toUpperCase()} conversation`,
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    message_count: 1,
  };

  useStore.setState({
    projects: [project],
    currentProject: project,
    documents: [{
      id: `document-${account}`,
      name: `Account ${account.toUpperCase()} document`,
      type: 'text',
      content: 'Private source',
      meta: {},
      status: 'ready',
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
      chunk_count: 1,
    }],
    conversations: [conversation],
    currentConversation: conversation,
    messages: [{
      id: `message-${account}`,
      conversation_id: conversation.id,
      role: 'user',
      content: `Account ${account.toUpperCase()} question`,
      citations: [],
      created_at: '2026-08-23T00:00:00Z',
    }],
    loadingProjects: true,
    loadingDocuments: true,
    loadingConversations: true,
    loadingMessages: true,
    uploadProgress: { [`upload-${account}`]: 50 },
    sidebarOpen: false,
    studioOpen: false,
    notifyOnProcessingComplete: false,
  });

  return project;
};

const expectWorkspaceRetired = (state: ReturnType<typeof useStore.getState> | null) => {
  expect(state).toMatchObject({
    projects: [],
    currentProject: null,
    documents: [],
    conversations: [],
    currentConversation: null,
    messages: [],
    loadingProjects: false,
    loadingDocuments: false,
    loadingConversations: false,
    loadingMessages: false,
    uploadProgress: {},
    sidebarOpen: false,
    studioOpen: false,
    notifyOnProcessingComplete: false,
  });
};

/** The headers the client put on its most recent request. */
const sentHeaders = (fetchMock: ReturnType<typeof vi.fn>): Headers => {
  const [, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return new Headers(init.headers);
};

const signIn = () => storeSession('a-signed-token', {
  username: 'ada',
  email: 'ada@example.com',
});

/** Replace `window.location` so a redirect is observable instead of a crash. */
const stubLocation = (pathname: string, onAssign?: () => void) => {
  const assign = vi.fn(onAssign);
  vi.stubGlobal('location', { ...window.location, pathname, assign });

  return assign;
};


beforeEach(() => {
  useStore.getState().resetForTests();
  window.localStorage.clear();
  clearSession();
});

afterEach(() => {
  useStore.getState().resetForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe('API client authorization', () => {
  it('sends the stored token on a JSON request', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock).get('Authorization')).toBe('Bearer a-signed-token');
  });

  it('sends the stored token on a write, alongside the content type', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: 'project-1',
      name: 'Research',
      description: null,
      meta_json: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      document_count: 0,
      conversation_count: 0,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.createProject({ name: 'Research' });

    expect(sentHeaders(fetchMock).get('Authorization')).toBe('Bearer a-signed-token');
    expect(sentHeaders(fetchMock).get('Content-Type')).toBe('application/json');
  });

  it('sends the stored token when downloading an export', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(new Response('# Summary'));
    vi.stubGlobal('fetch', fetchMock);

    await api.exportProjectSummary('project-1');

    expect(sentHeaders(fetchMock).get('Authorization')).toBe('Bearer a-signed-token');
  });

  it('sends the stored token when reading an export as text', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(new Response('# Summary'));
    vi.stubGlobal('fetch', fetchMock);

    await api.fetchProjectSummaryText('project-1');

    expect(sentHeaders(fetchMock).get('Authorization')).toBe('Bearer a-signed-token');
  });

  it('sends no Authorization header when nobody is signed in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock).get('Authorization')).toBeNull();
  });

  it('falls back to the mirrored key when only that one survived', async () => {
    // `storeSession` writes both; a browser that dropped one should still work.
    window.localStorage.setItem('auth_token', 'the-surviving-copy');
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock).get('Authorization')).toBe('Bearer the-surviving-copy');
  });
});


describe('a token the backend rejects', () => {
  it('gives up the session and returns to the login page', async () => {
    signIn();
    const assign = stubLocation('/projects/project-1');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: 'Could not validate credentials' },
      401,
    )));

    await expect(api.getProjects()).rejects.toThrow(
      'Could not validate credentials',
    );

    expect(window.localStorage.getItem('access_token')).toBeNull();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(document.cookie).not.toContain(`${AUTH_TOKEN_COOKIE}=a-signed-token`);
    expect(assign).toHaveBeenCalledWith('/login');
  });

  it('gives up the session on a rejected download too', async () => {
    signIn();
    const assign = stubLocation('/projects/project-1');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));

    await expect(api.exportProjectSummary('project-1')).rejects.toThrow();

    expect(window.localStorage.getItem('access_token')).toBeNull();
    expect(assign).toHaveBeenCalledWith('/login');
  });

  it('does not redirect a caller who is already on the login page', async () => {
    // Redirecting /login to /login reloads the page and throws away the error
    // the form was about to show.
    const assign = stubLocation('/login');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: 'Could not validate credentials' },
      401,
    )));

    await expect(api.getProjects()).rejects.toThrow();

    expect(assign).not.toHaveBeenCalled();
  });

  it('leaves a wrong password to the sign-in form', async () => {
    // /auth/token answers 401 for bad credentials. That is not an expired
    // session, and reloading the page would discard the message.
    const assign = stubLocation('/login');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: 'Incorrect username or password' },
      401,
    )));

    await expect(
      api.login({ username: 'ada', password: 'wrong' }),
    ).rejects.toThrow('Incorrect username or password');

    expect(assign).not.toHaveBeenCalled();
  });

  it('leaves a token check that fails to its caller', async () => {
    // Sign-in reads the account right after minting a token and handles its own
    // failure; a redirect from here would fight that.
    signIn();
    const assign = stubLocation('/login');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: 'Could not validate credentials' },
      401,
    )));

    await expect(api.getAccount('a-signed-token')).rejects.toThrow();

    expect(window.localStorage.getItem('access_token')).toBe('a-signed-token');
    expect(assign).not.toHaveBeenCalled();
  });
});

const protectedFetchHelpers = [
  { kind: 'JSON', request: () => api.getProjects() },
  { kind: 'blob', request: () => api.exportProjectSummary('project-a') },
  { kind: 'text', request: () => api.fetchProjectSummaryText('project-a') },
];

describe('deferred 401 session boundaries', () => {
  it.each(protectedFetchHelpers)(
    'does not abandon Account B when an Account A $kind response arrives late',
    async ({ request }) => {
      storeSession('account-a-token', {
        username: 'account-a',
        email: 'a@example.com',
      }, useStore.getState().clearAccountState);
      seedWorkspace('a');
      const pendingResponse = deferred<Response>();
      vi.stubGlobal('fetch', vi.fn(() => pendingResponse.promise));
      const assign = stubLocation('/projects/project-b');

      const pendingRequest = request();
      storeSession('account-b-token', {
        username: 'account-b',
        email: 'b@example.com',
      }, useStore.getState().clearAccountState);
      seedWorkspace('b');
      pendingResponse.resolve(jsonResponse({ detail: 'Could not validate credentials' }, 401));

      await expect(pendingRequest).rejects.toThrow('Could not validate credentials');
      expect(window.localStorage.getItem('access_token')).toBe('account-b-token');
      expect(window.localStorage.getItem('auth_token')).toBe('account-b-token');
      expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
        username: 'account-b',
        email: 'b@example.com',
      });
      expect(document.cookie).toContain(`${AUTH_TOKEN_COOKIE}=account-b-token`);
      expect(useStore.getState()).toMatchObject({
        projects: [expect.objectContaining({ id: 'project-b' })],
        currentProject: expect.objectContaining({ id: 'project-b' }),
        documents: [expect.objectContaining({ id: 'document-b' })],
        conversations: [expect.objectContaining({ id: 'conversation-b' })],
        currentConversation: expect.objectContaining({ id: 'conversation-b' }),
        messages: [expect.objectContaining({ id: 'message-b' })],
        loadingProjects: true,
        loadingDocuments: true,
        loadingConversations: true,
        loadingMessages: true,
        uploadProgress: { 'upload-b': 50 },
      });
      expect(assign).not.toHaveBeenCalled();
    },
  );

  it.each(protectedFetchHelpers)(
    'retires the active account before navigation for a $kind 401 response',
    async ({ request }) => {
      storeSession('account-a-token', {
        username: 'account-a',
        email: 'a@example.com',
      }, useStore.getState().clearAccountState);
      seedWorkspace('a');
      const pendingResponse = deferred<Response>();
      vi.stubGlobal('fetch', vi.fn(() => pendingResponse.promise));
      let stateAtNavigation: ReturnType<typeof useStore.getState> | null = null;
      const assign = stubLocation('/projects/project-a', () => {
        stateAtNavigation = useStore.getState();
      });

      const pendingRequest = request();
      pendingResponse.resolve(jsonResponse({ detail: 'Could not validate credentials' }, 401));

      await expect(pendingRequest).rejects.toThrow('Could not validate credentials');
      expectWorkspaceRetired(stateAtNavigation);
      expect(window.localStorage.getItem('access_token')).toBeNull();
      expect(window.localStorage.getItem('auth_token')).toBeNull();
      expect(window.localStorage.getItem('user')).toBeNull();
      expect(document.cookie).not.toContain(`${AUTH_TOKEN_COOKIE}=account-a-token`);
      expect(assign).toHaveBeenCalledWith('/login');
    },
  );

  it('does not abandon a replacement identity that reuses the dispatched token', async () => {
    storeSession('shared-token', {
      username: 'account-a',
      email: 'a@example.com',
    }, useStore.getState().clearAccountState);
    seedWorkspace('a');
    const pendingResponse = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn(() => pendingResponse.promise));
    const assign = stubLocation('/projects/project-b');

    const pendingRequest = api.getProjects();
    storeSession('shared-token', {
      username: 'account-b',
      email: 'b@example.com',
    }, useStore.getState().clearAccountState);
    seedWorkspace('b');
    pendingResponse.resolve(jsonResponse({ detail: 'Could not validate credentials' }, 401));

    await expect(pendingRequest).rejects.toThrow('Could not validate credentials');
    expect(window.localStorage.getItem('access_token')).toBe('shared-token');
    expect(useStore.getState().currentProject).toMatchObject({ id: 'project-b' });
    expect(assign).not.toHaveBeenCalled();
  });

  it.each(protectedFetchHelpers)(
    'retires the current cookie-only session before navigation for a $kind 401 response',
    async ({ request }) => {
      document.cookie = `${AUTH_TOKEN_COOKIE}=cookie-only-token; Path=/`;
      seedWorkspace('a');
      const pendingResponse = deferred<Response>();
      vi.stubGlobal('fetch', vi.fn(() => pendingResponse.promise));
      let stateAtNavigation: ReturnType<typeof useStore.getState> | null = null;
      const assign = stubLocation('/projects/project-a', () => {
        stateAtNavigation = useStore.getState();
      });

      const pendingRequest = request();
      pendingResponse.resolve(jsonResponse({ detail: 'Could not validate credentials' }, 401));

      await expect(pendingRequest).rejects.toThrow('Could not validate credentials');
      expectWorkspaceRetired(stateAtNavigation);
      expect(window.localStorage.getItem('access_token')).toBeNull();
      expect(window.localStorage.getItem('auth_token')).toBeNull();
      expect(document.cookie).not.toContain(`${AUTH_TOKEN_COOKIE}=cookie-only-token`);
      expect(assign).toHaveBeenCalledWith('/login');
    },
  );

  it.each(protectedFetchHelpers)(
    'does not abandon Account B when a cookie-only anonymous $kind response arrives late',
    async ({ request }) => {
      document.cookie = `${AUTH_TOKEN_COOKIE}=shared-token; Path=/`;
      seedWorkspace('a');
      const pendingResponse = deferred<Response>();
      vi.stubGlobal('fetch', vi.fn(() => pendingResponse.promise));
      const assign = stubLocation('/projects/project-b');

      const pendingRequest = request();
      storeSession('shared-token', {
        username: 'account-b',
        email: 'b@example.com',
      }, useStore.getState().clearAccountState);
      seedWorkspace('b');
      pendingResponse.resolve(jsonResponse({ detail: 'Could not validate credentials' }, 401));

      await expect(pendingRequest).rejects.toThrow('Could not validate credentials');
      expect(window.localStorage.getItem('access_token')).toBe('shared-token');
      expect(document.cookie).toContain(`${AUTH_TOKEN_COOKIE}=shared-token`);
      expect(useStore.getState().currentProject).toMatchObject({ id: 'project-b' });
      expect(assign).not.toHaveBeenCalled();
    },
  );

  it.each(protectedFetchHelpers)(
    'leaves a truly signed-out $kind caller on its current page after a 401 response',
    async ({ request }) => {
      const assign = stubLocation('/projects');
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
        { detail: 'Could not validate credentials' },
        401,
      )));

      await expect(request()).rejects.toThrow('Could not validate credentials');

      expect(assign).not.toHaveBeenCalled();
      expect(document.cookie).not.toContain(`${AUTH_TOKEN_COOKIE}=`);
    },
  );
});
