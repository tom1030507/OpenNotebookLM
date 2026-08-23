// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  AUTH_TOKEN_COOKIE,
  clearSession,
  readAccessToken,
  storeSession,
} from './session';
import useStore from '@/store/useStore';
import type { Conversation, Document, Project } from './api';


const cookieValue = (name: string) => document.cookie
  .split('; ')
  .find((entry) => entry.startsWith(`${name}=`))
  ?.slice(name.length + 1);


const seedAccountState = () => {
  const project = {
    id: 'project-a',
    name: 'Account A project',
    description: null,
    meta_json: {},
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    document_count: 1,
    conversation_count: 1,
  };
  const conversation = {
    id: 'conversation-a',
    project_id: project.id,
    title: 'Account A conversation',
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    message_count: 1,
  };

  useStore.setState({
    projects: [project],
    currentProject: project,
    documents: [{
      id: 'document-a',
      name: 'Account A document',
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
      id: 'message-a',
      conversation_id: conversation.id,
      role: 'user',
      content: 'Private question',
      citations: [],
      created_at: '2026-08-23T00:00:00Z',
    }],
    loadingProjects: true,
    loadingDocuments: true,
    loadingConversations: true,
    loadingMessages: true,
    uploadProgress: { 'document-a-upload': 50 },
    sidebarOpen: false,
    studioOpen: false,
    notifyOnProcessingComplete: false,
  });
};


const expectAccountStateCleared = () => {
  expect(useStore.getState()).toMatchObject({
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


const expectReplacementSession = () => {
  expect(readAccessToken()).toBe('account-b-token');
  expect(window.localStorage.getItem('auth_token')).toBe('account-b-token');
  expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
    username: 'account-b',
    email: 'b@example.com',
  });
  expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('account-b-token');
};


beforeEach(() => {
  window.localStorage.clear();
  clearSession();
  useStore.getState().resetForTests();
});

afterEach(() => {
  useStore.getState().resetForTests();
  vi.restoreAllMocks();
});


describe('browser session', () => {
  it('mirrors the token into a cookie so middleware can see it', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('a-signed-token');
  });

  it('keeps the token in localStorage for the API client', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    expect(window.localStorage.getItem('access_token')).toBe('a-signed-token');
    expect(window.localStorage.getItem('auth_token')).toBe('a-signed-token');
    expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
      username: 'ada',
      email: 'ada@example.com',
    });
  });

  it('clears the cookie and the stored account on sign-out', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    clearSession();

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBeUndefined();
    expect(window.localStorage.getItem('access_token')).toBeNull();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(window.localStorage.getItem('user')).toBeNull();
  });

  it('escapes a token that would otherwise break the cookie header', () => {
    storeSession('token with; semicolon', { username: 'ada', email: 'ada@example.com' });

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe(
      encodeURIComponent('token with; semicolon'),
    );
  });

  it('reads back the token the API client has to send', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    expect(readAccessToken()).toBe('a-signed-token');
  });

  it('falls back to the mirrored key when the first one is gone', () => {
    window.localStorage.setItem('auth_token', 'the-surviving-copy');

    expect(readAccessToken()).toBe('the-surviving-copy');
  });

  it('has no token to read once the session is cleared', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    clearSession();

    expect(readAccessToken()).toBeNull();
  });

  it('fails closed on malformed stored user data while persisting the replacement session', () => {
    const project: Project = {
      id: 'project-a',
      name: 'Account A project',
      description: null,
      meta_json: {},
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
      document_count: 1,
      conversation_count: 1,
    };
    const document: Document = {
      id: 'document-a',
      name: 'Account A document',
      type: 'text',
      content: 'Private source',
      meta: {},
      status: 'ready',
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
      chunk_count: 1,
    };
    const conversation: Conversation = {
      id: 'conversation-a',
      project_id: project.id,
      title: 'Account A conversation',
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
      message_count: 1,
    };
    window.localStorage.setItem('user', '{malformed');
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [document],
      conversations: [conversation],
      currentConversation: conversation,
      messages: [{
        id: 'message-a',
        conversation_id: conversation.id,
        role: 'user',
        content: 'Private question',
        citations: [],
        created_at: '2026-08-23T00:00:00Z',
      }],
      loadingProjects: true,
      loadingDocuments: true,
      loadingConversations: true,
      loadingMessages: true,
      uploadProgress: { 'document-a-upload': 50 },
      sidebarOpen: false,
      studioOpen: false,
      notifyOnProcessingComplete: false,
    });

    storeSession(
      'account-b-token',
      { username: 'account-b', email: 'b@example.com' },
      useStore.getState().clearAccountState,
    );

    expect(useStore.getState()).toMatchObject({
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
    expect(readAccessToken()).toBe('account-b-token');
    expect(window.localStorage.getItem('auth_token')).toBe('account-b-token');
    expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
      username: 'account-b',
      email: 'b@example.com',
    });
    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('account-b-token');
  });

  it.each([
    ['null', 'null'],
    ['empty object', '{}'],
    ['numeric username', JSON.stringify({ username: 42, email: 'a@example.com' })],
    ['blank username', JSON.stringify({ username: '   ', email: 'a@example.com' })],
    ['missing email', JSON.stringify({ username: 'account-b' })],
  ])('fails closed on valid JSON with an invalid stored user shape: %s', (_label, storedUser) => {
    window.localStorage.setItem('user', storedUser);
    seedAccountState();

    storeSession(
      'account-b-token',
      { username: 'account-b', email: 'b@example.com' },
      useStore.getState().clearAccountState,
    );

    expectAccountStateCleared();
    expectReplacementSession();
  });

  it('fails closed when reading stored user data throws before persisting a replacement session', () => {
    seedAccountState();
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Storage read denied');
    });

    storeSession(
      'account-b-token',
      { username: 'account-b', email: 'b@example.com' },
      useStore.getState().clearAccountState,
    );
    getItem.mockRestore();

    expectAccountStateCleared();
    expectReplacementSession();
  });
});
