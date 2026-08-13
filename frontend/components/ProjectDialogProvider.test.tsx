// @vitest-environment jsdom

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Project } from '@/lib/api';

const apiMock = vi.hoisted(() => ({
  createProject: vi.fn(),
  getConversations: vi.fn(),
  getDocuments: vi.fn(),
  getProjects: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ default: apiMock }));

import ProjectDialogProvider from './ProjectDialogProvider';
import TopNav from './layout/TopNav';
import SourcesPanel from './layout/SourcesPanel';
import useStore from '@/store/useStore';

const createdProject: Project = {
  id: 'project-created',
  name: '研究計畫',
  description: '新的專案',
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });

  return { promise, reject, resolve };
};

const renderProjectCreationTriggers = () => render(
  React.createElement(
    ProjectDialogProvider,
    null,
    React.createElement(TopNav),
    React.createElement(SourcesPanel),
  ),
);

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  apiMock.getProjects.mockResolvedValue([]);
  apiMock.getDocuments.mockResolvedValue([]);
  apiMock.getConversations.mockResolvedValue([]);
  useStore.setState({
    projects: [],
    currentProject: null,
    loadingProjects: false,
    documents: [],
    loadingDocuments: false,
    uploadProgress: {},
    conversations: [],
    currentConversation: null,
    messages: [],
    loadingConversations: false,
    loadingMessages: false,
    sidebarOpen: true,
    studioOpen: true,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ProjectDialogProvider', () => {
  it('opens one named dialog from each project creation trigger without browser prompts', async () => {
    const user = userEvent.setup();
    const promptSpy = vi.spyOn(window, 'prompt');
    const alertSpy = vi.spyOn(window, 'alert');
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: '新增專案' }));
    expect(screen.getAllByRole('dialog', { name: '建立新專案' })).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '關閉建立新專案對話框' }));
    expect(screen.queryByRole('dialog', { name: '建立新專案' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'New Project' }));

    expect(screen.getAllByRole('dialog', { name: '建立新專案' })).toHaveLength(1);
    expect(promptSpy).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('selects the created project and closes the dialog as soon as creation succeeds', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockResolvedValue(createdProject);
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: 'New Project' }));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: '建立專案' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '建立新專案' })).toBeNull();
    });
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe(createdProject.id);
  });

  it('keeps the dialog open and displays the API error when creation fails', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockRejectedValue(new Error('伺服器暫時無法建立專案'));
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: '新增專案' }));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), '研究計畫');
    await user.click(screen.getByRole('button', { name: '建立專案' }));

    expect(await screen.findByText('伺服器暫時無法建立專案')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: '建立新專案' })).not.toBeNull();
  });

  it('clears a creation error after closing and reopening the dialog', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockRejectedValue(new Error('伺服器暫時無法建立專案'));
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: '新增專案' }));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), '研究計畫');
    await user.click(screen.getByRole('button', { name: '建立專案' }));
    await screen.findByText('伺服器暫時無法建立專案');

    await user.click(screen.getByRole('button', { name: '關閉建立新專案對話框' }));
    await user.click(screen.getByRole('button', { name: 'New Project' }));

    expect(screen.queryByText('伺服器暫時無法建立專案')).toBeNull();
  });

  it('keeps the dialog open when its close control is pressed during a pending successful creation', async () => {
    const user = userEvent.setup();
    const creation = deferred<Project>();
    apiMock.createProject.mockReturnValue(creation.promise);
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: '新增專案' }));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: '建立專案' }));

    const closeButton = screen.getByRole('button', {
      name: '關閉建立新專案對話框',
    }) as HTMLButtonElement;
    const cancelButton = screen.getByRole('button', { name: '取消' }) as HTMLButtonElement;

    expect(closeButton.disabled).toBe(true);
    expect(cancelButton.disabled).toBe(true);
    await user.click(closeButton);
    expect(screen.getByRole('dialog', { name: '建立新專案' })).not.toBeNull();

    creation.resolve(createdProject);

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '建立新專案' })).toBeNull();
    });
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe(createdProject.id);
  });

  it('keeps an API error in the pending creation dialog until the request fails', async () => {
    const user = userEvent.setup();
    const creation = deferred<Project>();
    apiMock.createProject.mockReturnValue(creation.promise);
    renderProjectCreationTriggers();

    await user.click(screen.getByRole('button', { name: '新增專案' }));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: '建立專案' }));

    const closeButton = screen.getByRole('button', {
      name: '關閉建立新專案對話框',
    }) as HTMLButtonElement;
    expect(closeButton.disabled).toBe(true);
    await user.click(closeButton);
    expect(screen.getByRole('dialog', { name: '建立新專案' })).not.toBeNull();

    creation.reject(new Error('伺服器暫時無法建立專案'));

    expect(await screen.findByText('伺服器暫時無法建立專案')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: '建立新專案' })).not.toBeNull();
    expect((screen.getByRole('button', {
      name: '關閉建立新專案對話框',
    }) as HTMLButtonElement).disabled).toBe(false);
  });
});
