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

/** The headers the client put on its most recent request. */
const sentHeaders = (fetchMock: ReturnType<typeof vi.fn>): Record<string, string> => {
  const [, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return init.headers as Record<string, string>;
};

const signIn = () => storeSession('a-signed-token', {
  username: 'ada',
  email: 'ada@example.com',
});

/** Replace `window.location` so a redirect is observable instead of a crash. */
const stubLocation = (pathname: string) => {
  const assign = vi.fn();
  vi.stubGlobal('location', { ...window.location, pathname, assign });

  return assign;
};


beforeEach(() => {
  window.localStorage.clear();
  clearSession();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe('API client authorization', () => {
  it('sends the stored token on a JSON request', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer a-signed-token');
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

    expect(sentHeaders(fetchMock)).toMatchObject({
      Authorization: 'Bearer a-signed-token',
      'Content-Type': 'application/json',
    });
  });

  it('sends the stored token when downloading an export', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(new Response('# Summary'));
    vi.stubGlobal('fetch', fetchMock);

    await api.exportProjectSummary('project-1');

    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer a-signed-token');
  });

  it('sends the stored token when reading an export as text', async () => {
    signIn();
    const fetchMock = vi.fn().mockResolvedValue(new Response('# Summary'));
    vi.stubGlobal('fetch', fetchMock);

    await api.fetchProjectSummaryText('project-1');

    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer a-signed-token');
  });

  it('sends no Authorization header when nobody is signed in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock)).not.toHaveProperty('Authorization');
  });

  it('falls back to the mirrored key when only that one survived', async () => {
    // `storeSession` writes both; a browser that dropped one should still work.
    window.localStorage.setItem('auth_token', 'the-surviving-copy');
    const fetchMock = vi.fn().mockResolvedValue(emptyProjectList());
    vi.stubGlobal('fetch', fetchMock);

    await api.getProjects();

    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer the-surviving-copy');
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
