// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LoginPage from './page';
import api from '@/lib/api';
import { AUTH_TOKEN_COOKIE } from '@/lib/session';
import useStore from '@/store/useStore';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));


const cookieValue = (name: string) => document.cookie
  .split('; ')
  .find((entry) => entry.startsWith(`${name}=`))
  ?.slice(name.length + 1);


const fillIn = (label: RegExp | string, value: string) => {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
};


// In either mode one button submits and the other toggles, so the submit
// button is the one whose name matches the mode.
const submit = (name: 'Login' | 'Register' = 'Login') => fireEvent.click(
  screen.getByRole('button', { name }),
);

const switchToRegister = () => fireEvent.click(
  screen.getByRole('button', { name: 'Register' }),
);


beforeEach(() => {
  push.mockClear();
  window.localStorage.clear();
  document.cookie = `${AUTH_TOKEN_COOKIE}=; Path=/; Max-Age=0`;
  useStore.getState().resetForTests();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


describe('login page', () => {
  it('signs in through the shared API client and opens the workspace', async () => {
    const login = vi.spyOn(api, 'login').mockResolvedValue({
      access_token: 'a-signed-token',
      token_type: 'bearer',
    });
    vi.spyOn(api, 'getAccount').mockResolvedValue({
      id: 'user-1',
      username: 'ada',
      email: 'ada@example.com',
      created_at: '2026-01-01T00:00:00Z',
    });

    render(<LoginPage />);
    fillIn(/username/i, 'ada');
    fillIn(/^password$/i, 'lovelace-1843');
    submit();

    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(login).toHaveBeenCalledWith({
      username: 'ada',
      password: 'lovelace-1843',
    });
    expect(window.localStorage.getItem('auth_token')).toBe('a-signed-token');
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('a-signed-token');
    expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
      username: 'ada',
      email: 'ada@example.com',
    });
  });

  it('clears account A workspace state before storing account B', async () => {
    window.localStorage.setItem('user', JSON.stringify({
      username: 'account-a',
      email: 'a@example.com',
    }));
    useStore.setState({
      projects: [{
        id: 'project-a',
        name: 'Account A project',
        description: null,
        meta_json: {},
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        document_count: 1,
        conversation_count: 1,
      }],
      currentProject: {
        id: 'project-a',
        name: 'Account A project',
        description: null,
        meta_json: {},
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        document_count: 1,
        conversation_count: 1,
      },
      documents: [{
        id: 'document-a',
        name: 'Account A document',
        type: 'text',
        meta: {},
        status: 'ready',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        chunk_count: 1,
      }],
      conversations: [{
        id: 'conversation-a',
        project_id: 'project-a',
        title: 'Account A conversation',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        message_count: 1,
      }],
      currentConversation: {
        id: 'conversation-a',
        project_id: 'project-a',
        title: 'Account A conversation',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        message_count: 1,
      },
      messages: [{
        id: 'message-a',
        conversation_id: 'conversation-a',
        role: 'user',
        content: 'Account A message',
        citations: [],
        created_at: '2026-08-23T00:00:00Z',
      }],
      sidebarOpen: false,
      studioOpen: false,
      notifyOnProcessingComplete: false,
    });
    vi.spyOn(api, 'login').mockResolvedValue({
      access_token: 'account-b-token',
      token_type: 'bearer',
    });
    vi.spyOn(api, 'getAccount').mockResolvedValue({
      id: 'user-b',
      username: 'account-b',
      email: 'b@example.com',
      created_at: '2026-08-23T00:00:00Z',
    });

    render(<LoginPage />);
    fillIn(/username/i, 'account-b');
    fillIn(/^password$/i, 'account-b-password');
    submit();

    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(useStore.getState()).toMatchObject({
      projects: [],
      currentProject: null,
      documents: [],
      conversations: [],
      currentConversation: null,
      messages: [],
      sidebarOpen: false,
      studioOpen: false,
      notifyOnProcessingComplete: false,
    });
  });

  it('clears stale workspace state when the first project fetch fails', async () => {
    useStore.setState({
      projects: [{
        id: 'project-a',
        name: 'Account A project',
        description: null,
        meta_json: {},
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        document_count: 1,
        conversation_count: 1,
      }],
      currentProject: {
        id: 'project-a',
        name: 'Account A project',
        description: null,
        meta_json: {},
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        document_count: 1,
        conversation_count: 1,
      },
      documents: [{
        id: 'document-a',
        name: 'Account A document',
        type: 'text',
        meta: {},
        status: 'ready',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        chunk_count: 1,
      }],
      conversations: [{
        id: 'conversation-a',
        project_id: 'project-a',
        title: 'Account A conversation',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        message_count: 1,
      }],
      currentConversation: {
        id: 'conversation-a',
        project_id: 'project-a',
        title: 'Account A conversation',
        created_at: '2026-08-23T00:00:00Z',
        updated_at: '2026-08-23T00:00:00Z',
        message_count: 1,
      },
      messages: [{
        id: 'message-a',
        conversation_id: 'conversation-a',
        role: 'user',
        content: 'Account A message',
        citations: [],
        created_at: '2026-08-23T00:00:00Z',
      }],
      sidebarOpen: false,
      studioOpen: false,
      notifyOnProcessingComplete: false,
    });
    vi.spyOn(api, 'getProjects').mockRejectedValue(new Error('Network unavailable'));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    await act(async () => {
      await useStore.getState().fetchProjects();
    });

    expect(useStore.getState()).toMatchObject({
      projects: [],
      currentProject: null,
      documents: [],
      conversations: [],
      currentConversation: null,
      messages: [],
      sidebarOpen: false,
      studioOpen: false,
      notifyOnProcessingComplete: false,
    });
  });

  it('shows a wrong password as an error in the form and stays put', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(
      new Error('Incorrect username or password'),
    );

    render(<LoginPage />);
    fillIn(/username/i, 'ada');
    fillIn(/^password$/i, 'not-my-password');
    submit();

    expect(await screen.findByText('Incorrect username or password')).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBeUndefined();
    expect(screen.getByRole('button', { name: 'Login' })).toBeTruthy();
  });

  it('registers and then signs the new account in', async () => {
    const register = vi.spyOn(api, 'register').mockResolvedValue({
      id: 'user-1',
      username: 'grace',
      email: 'grace@example.com',
      created_at: '2026-01-01T00:00:00Z',
    });
    vi.spyOn(api, 'login').mockResolvedValue({
      access_token: 'a-new-token',
      token_type: 'bearer',
    });

    render(<LoginPage />);
    switchToRegister();
    fillIn(/username/i, 'grace');
    fillIn(/email/i, 'grace@example.com');
    fillIn(/^password$/i, 'hopper-secret');
    fillIn(/confirm password/i, 'hopper-secret');
    submit('Register');

    await waitFor(() => expect(push).toHaveBeenCalledWith('/'));
    expect(register).toHaveBeenCalledWith({
      username: 'grace',
      email: 'grace@example.com',
      password: 'hopper-secret',
    });
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('a-new-token');
  });

  it('reports a rejected registration without leaving a session behind', async () => {
    vi.spyOn(api, 'register').mockRejectedValue(
      new Error('That username or email is already registered'),
    );
    const login = vi.spyOn(api, 'login');

    render(<LoginPage />);
    switchToRegister();
    fillIn(/username/i, 'grace');
    fillIn(/email/i, 'grace@example.com');
    fillIn(/^password$/i, 'hopper-secret');
    fillIn(/confirm password/i, 'hopper-secret');
    submit('Register');

    expect(
      await screen.findByText('That username or email is already registered'),
    ).toBeTruthy();
    expect(login).not.toHaveBeenCalled();
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBeUndefined();
  });

  it('catches mismatched passwords before calling the API', async () => {
    const register = vi.spyOn(api, 'register');

    render(<LoginPage />);
    switchToRegister();
    fillIn(/username/i, 'grace');
    fillIn(/email/i, 'grace@example.com');
    fillIn(/^password$/i, 'hopper-secret');
    fillIn(/confirm password/i, 'hopper-secrets');
    submit('Register');

    expect(await screen.findByText('Passwords do not match')).toBeTruthy();
    expect(register).not.toHaveBeenCalled();
  });

  it('offers no way in that skips the backend', () => {
    // A session the backend never issued is refused by every API route, so a
    // client-side shortcut lands straight back here. There is no shortcut.
    render(<LoginPage />);

    expect(screen.queryByRole('button', { name: /Quick Demo Access/ })).toBeNull();
    expect(screen.queryByText(/admin123/)).toBeNull();
  });

  it('sends the old demo credentials to the backend like any others', async () => {
    const login = vi.spyOn(api, 'login').mockRejectedValue(
      new Error('Incorrect username or password'),
    );

    render(<LoginPage />);
    fillIn(/username/i, 'admin');
    fillIn(/^password$/i, 'admin123');
    submit();

    expect(await screen.findByText('Incorrect username or password')).toBeTruthy();
    expect(login).toHaveBeenCalledWith({
      username: 'admin',
      password: 'admin123',
    });
    expect(push).not.toHaveBeenCalled();
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBeUndefined();
  });
});
