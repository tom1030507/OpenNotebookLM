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

let consoleError: ReturnType<typeof vi.spyOn>;

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
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
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
  consoleError.mockRestore();
});

describe('ProjectDialogProvider', () => {
  it('opens one named dialog from either project creation trigger', async () => {
    const user = userEvent.setup();
    renderProjectCreationTriggers();

    await user.click(screen.getByTitle('New Project'));
    await user.click(screen.getByRole('button', { name: 'New Project' }));

    expect(screen.getAllByRole('dialog', { name: '建立新專案' })).toHaveLength(1);
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

    await user.click(screen.getByTitle('New Project'));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), '研究計畫');
    await user.click(screen.getByRole('button', { name: '建立專案' }));

    expect(await screen.findByText('伺服器暫時無法建立專案')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: '建立新專案' })).not.toBeNull();
  });

  it('clears a creation error after closing and reopening the dialog', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockRejectedValue(new Error('伺服器暫時無法建立專案'));
    renderProjectCreationTriggers();

    await user.click(screen.getByTitle('New Project'));
    await user.type(screen.getByRole('textbox', { name: /專案名稱/ }), '研究計畫');
    await user.click(screen.getByRole('button', { name: '建立專案' }));
    await screen.findByText('伺服器暫時無法建立專案');

    await user.click(screen.getByRole('button', { name: '關閉建立專案對話框' }));
    await user.click(screen.getByRole('button', { name: 'New Project' }));

    expect(screen.queryByText('伺服器暫時無法建立專案')).toBeNull();
  });
});
