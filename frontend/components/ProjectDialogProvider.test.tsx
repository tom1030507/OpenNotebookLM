// @vitest-environment jsdom

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Project } from '@/lib/api';

const apiMock = vi.hoisted(() => ({
  createProject: vi.fn(),
  updateProject: vi.fn(),
  duplicateProject: vi.fn(),
  getConversations: vi.fn(),
  getDocuments: vi.fn(),
  getProjects: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ default: apiMock }));

import ProjectDialogProvider from './ProjectDialogProvider';
import TopNav from './layout/TopNav';
import SourcesPanel from './layout/SourcesPanel';
import ChatArea from './chat/ChatArea';
import useStore from '@/store/useStore';

// TopNav navigates on sign-out.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));


const createdProject: Project = {
  id: 'project-created',
  name: 'Research plan',
  description: 'New project',
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
  role: 'owner',
  cover_emoji: '📚',
  cover_color: 'blue',
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

describe('project covers and duplication', () => {
  it('renames a project and edits its cover through the shared project dialog', async () => {
    const user = userEvent.setup();
    const original = { ...createdProject, cover_emoji: '📚', cover_color: 'blue' } as Project;
    const updated = { ...original, name: 'Cell biology', cover_emoji: '🧠', cover_color: 'violet' };
    apiMock.getProjects.mockResolvedValue([original]);
    apiMock.updateProject.mockResolvedValue(updated);
    useStore.setState({ projects: [original], currentProject: original });
    renderProjectCreationTriggers();

    await user.click(await screen.findByRole('button', { name: 'Edit Project' }));
    expect(screen.getByRole('dialog', { name: 'Edit Project' })).not.toBeNull();
    await user.clear(screen.getByLabelText('Project Name'));
    await user.type(screen.getByLabelText('Project Name'), 'Cell biology');
    await user.selectOptions(screen.getByLabelText('Cover emoji'), '🧠');
    await user.selectOptions(screen.getByLabelText('Cover color'), 'violet');
    await user.click(screen.getByRole('button', { name: 'Save Project' }));

    await waitFor(() => expect(apiMock.updateProject).toHaveBeenCalledWith(original.id, {
      name: 'Cell biology',
      cover_emoji: '🧠',
      cover_color: 'violet',
      description: original.description,
    }));
    expect(useStore.getState().currentProject?.cover_color).toBe('violet');
    expect(useStore.getState().currentProject?.name).toBe('Cell biology');
  });

  it('duplicates and selects the new project', async () => {
    const user = userEvent.setup();
    const original = { ...createdProject, cover_emoji: '📚', cover_color: 'blue' } as Project;
    const duplicate = { ...original, id: 'project-copy', name: 'Research plan (copy)' };
    apiMock.getProjects.mockResolvedValue([original]);
    apiMock.duplicateProject.mockResolvedValue(duplicate);
    useStore.setState({ projects: [original], currentProject: original });
    renderProjectCreationTriggers();

    await user.click(await screen.findByRole('button', { name: 'Duplicate Project' }));

    await waitFor(() => expect(useStore.getState().currentProject?.id).toBe(duplicate.id));
    expect(apiMock.duplicateProject).toHaveBeenCalledWith(original.id);
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe(duplicate.id);
  });

  it('shows each project emoji and the selected cover in the project list', async () => {
    const original = { ...createdProject, cover_emoji: '📚', cover_color: 'blue' } as Project;
    apiMock.getProjects.mockResolvedValue([original]);
    useStore.setState({ projects: [original], currentProject: original });
    const { container } = renderProjectCreationTriggers();

    expect(await screen.findByRole('option', { name: '📚 Research plan' })).not.toBeNull();
    expect(screen.getAllByRole('img', { name: 'Project cover: 📚' }).some(
      (cover) => cover.getAttribute('data-cover-color') === 'blue',
    )).toBe(true);
    const option = container.querySelector('option[value="project-created"]');
    expect(option?.textContent).toContain('📚');
    expect(option?.getAttribute('data-cover-color')).toBe('blue');
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

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[0]);
    expect(screen.getAllByRole('dialog', { name: 'Create New Project' })).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Close create project dialog' }));
    expect(screen.queryByRole('dialog', { name: 'Create New Project' })).toBeNull();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[1]);

    expect(screen.getAllByRole('dialog', { name: 'Create New Project' })).toHaveLength(1);
    expect(promptSpy).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('selects the created project and closes the dialog as soon as creation succeeds', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockResolvedValue(createdProject);
    renderProjectCreationTriggers();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[1]);
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: 'Create Project' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create New Project' })).toBeNull();
    });
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe(createdProject.id);
  });

  it('moves focus from the central creation CTA to Upload sources after creation', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockResolvedValue(createdProject);
    render(
      <ProjectDialogProvider>
        <ChatArea onAddSourcesOpenChange={() => undefined} />
      </ProjectDialogProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'New Project' }));
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: 'Create Project' }));

    const uploadSources = await screen.findByRole('button', { name: 'Upload sources' });
    expect(document.activeElement).toBe(uploadSources);
  });

  it('keeps the dialog open and displays the API error when creation fails', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockRejectedValue(new Error('The server could not create the project'));
    renderProjectCreationTriggers();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[0]);
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), 'Research plan');
    await user.click(screen.getByRole('button', { name: 'Create Project' }));

    expect(await screen.findByText('The server could not create the project')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).not.toBeNull();
  });

  it('clears a creation error after closing and reopening the dialog', async () => {
    const user = userEvent.setup();
    apiMock.createProject.mockRejectedValue(new Error('The server could not create the project'));
    renderProjectCreationTriggers();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[0]);
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), 'Research plan');
    await user.click(screen.getByRole('button', { name: 'Create Project' }));
    await screen.findByText('The server could not create the project');

    await user.click(screen.getByRole('button', { name: 'Close create project dialog' }));
    await user.click(screen.getAllByRole('button', { name: 'New Project' })[1]);

    expect(screen.queryByText('The server could not create the project')).toBeNull();
  });

  it('keeps the dialog open when its close control is pressed during a pending successful creation', async () => {
    const user = userEvent.setup();
    const creation = deferred<Project>();
    apiMock.createProject.mockReturnValue(creation.promise);
    renderProjectCreationTriggers();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[0]);
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: 'Create Project' }));

    const closeButton = screen.getByRole('button', {
      name: 'Close create project dialog',
    }) as HTMLButtonElement;
    const cancelButton = screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement;

    expect(closeButton.disabled).toBe(true);
    expect(cancelButton.disabled).toBe(true);
    await user.click(closeButton);
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).not.toBeNull();

    creation.resolve(createdProject);

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create New Project' })).toBeNull();
    });
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe(createdProject.id);
  });

  it('keeps an API error in the pending creation dialog until the request fails', async () => {
    const user = userEvent.setup();
    const creation = deferred<Project>();
    apiMock.createProject.mockReturnValue(creation.promise);
    renderProjectCreationTriggers();

    await user.click(screen.getAllByRole('button', { name: 'New Project' })[0]);
    await user.type(screen.getByRole('textbox', { name: /Project Name/ }), createdProject.name);
    await user.click(screen.getByRole('button', { name: 'Create Project' }));

    const closeButton = screen.getByRole('button', {
      name: 'Close create project dialog',
    }) as HTMLButtonElement;
    expect(closeButton.disabled).toBe(true);
    await user.click(closeButton);
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).not.toBeNull();

    creation.reject(new Error('The server could not create the project'));

    expect(await screen.findByText('The server could not create the project')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).not.toBeNull();
    expect((screen.getByRole('button', {
      name: 'Close create project dialog',
    }) as HTMLButtonElement).disabled).toBe(false);
  });
});
