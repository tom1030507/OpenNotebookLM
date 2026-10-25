// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ProjectDialogProvider from '../ProjectDialogProvider';
import SourcesPanel from './SourcesPanel';
import api, { type Document, type Project, type ProjectSourceGroup } from '@/lib/api';
import useStore, { selectedSourceIds } from '@/store/useStore';

const project = (id: string, tags: string[] = [], role: Project['role'] = 'owner'): Project => ({
  id,
  name: `Project ${id}`,
  description: null,
  meta_json: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
  role,
  tags,
});

const document = (id: string, status: Document['status'] = 'ready'): Document => ({
  id,
  name: `Source ${id}`,
  type: 'pdf',
  isOwnedByCaller: true,
  meta: {},
  status,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  chunk_count: 1,
});

const renderPanel = () => render(
  <ProjectDialogProvider>
    <SourcesPanel isAddSourcesOpen={false} onAddSourcesOpenChange={() => {}} />
  </ProjectDialogProvider>,
);

beforeEach(() => {
  const currentProject = project('one');
  useStore.setState({
    projects: [currentProject],
    currentProject,
    documents: [],
    loadingDocuments: false,
    fetchProjects: async () => undefined,
  });
  vi.spyOn(api, 'getProjectSourceGroups').mockResolvedValue([]);
  vi.spyOn(api, 'getWatchedFolder').mockResolvedValue({ enabled: false, path: null });
});

afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
  vi.restoreAllMocks();
});

describe('project tags and source groups', () => {
  it('filters project choices by any selected personal tag and keeps the current project available', () => {
    const current = project('one', ['Research']);
    useStore.setState({
      projects: [current, project('two', ['Personal']), project('three', ['Priority'])],
      currentProject: current,
    });
    renderPanel();

    fireEvent.click(screen.getByText('Filter projects by tag'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Filter by tag Research' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Filter by tag Priority' }));

    const selector = screen.getByRole('combobox', { name: 'Select a project' });
    expect(within(selector).getByRole('option', { name: 'Project one' })).toBeTruthy();
    expect(within(selector).getByRole('option', { name: 'Project three' })).toBeTruthy();
    expect(within(selector).queryByRole('option', { name: 'Project two' })).toBeNull();
  });

  it('lets a viewer edit their own project tags', async () => {
    const current = project('one', ['Research'], 'viewer');
    useStore.setState({ projects: [current], currentProject: current });
    vi.spyOn(api, 'updateProjectTags').mockResolvedValue(['Research', 'Urgent']);
    renderPanel();

    fireEvent.click(screen.getByText('My project tags'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Add a tag' }), {
      target: { value: 'Urgent' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add tag' }));

    await waitFor(() => expect(api.updateProjectTags).toHaveBeenCalledWith('one', ['Research', 'Urgent']));
    expect(useStore.getState().currentProject?.tags).toEqual(['Research', 'Urgent']);
    expect(screen.getByRole('button', { name: 'Remove tag Urgent' })).toBeTruthy();
  });

  it('selects only ready sources in a group and supports moving sources', async () => {
    const current = project('one');
    const group: ProjectSourceGroup = {
      id: 'group-1', name: 'Reading list', document_ids: ['ready', 'failed'],
    };
    useStore.setState({
      projects: [current],
      currentProject: current,
      documents: [document('ready'), document('failed', 'error'), document('outside')],
      deselectedSources: { one: ['ready', 'outside'] },
    });
    vi.spyOn(api, 'getProjectSourceGroups').mockResolvedValue([group]);
    vi.spyOn(api, 'setDocumentSourceGroup').mockResolvedValue([
      { ...group, document_ids: ['ready', 'outside'] },
    ]);
    renderPanel();

    const groupCheckbox = await screen.findByRole('checkbox', { name: 'Select sources in Reading list' });
    fireEvent.click(groupCheckbox);
    expect(useStore.getState().deselectedSources.one).toEqual(['outside']);
    expect(selectedSourceIds(useStore.getState())).toEqual(['ready']);

    fireEvent.change(screen.getByRole('combobox', { name: 'Move Source outside to group' }), {
      target: { value: 'group-1' },
    });
    await waitFor(() => expect(api.setDocumentSourceGroup).toHaveBeenCalledWith(
      'one', 'outside', 'group-1',
    ));
    await waitFor(() => {
      expect((screen.getByRole('combobox', {
        name: 'Move Source outside to group',
      }) as HTMLSelectElement).value).toBe('group-1');
    });
  });

  it('creates, renames and deletes shared groups', async () => {
    const current = project('one');
    useStore.setState({ projects: [current], currentProject: current });
    vi.spyOn(api, 'createProjectSourceGroup').mockResolvedValue({
      id: 'group-1', name: 'To read', document_ids: [],
    });
    vi.spyOn(api, 'renameProjectSourceGroup').mockResolvedValue({
      id: 'group-1', name: 'Read later', document_ids: [],
    });
    vi.spyOn(api, 'deleteProjectSourceGroup').mockResolvedValue(undefined);
    vi.stubGlobal('prompt', vi.fn().mockReturnValue('Read later'));
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
    renderPanel();

    fireEvent.click(screen.getByText('Source groups'));
    fireEvent.change(screen.getByRole('textbox', { name: 'New source group' }), {
      target: { value: 'To read' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create group' }));
    expect((await screen.findAllByText('To read')).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Rename To read' }));
    await waitFor(() => expect(api.renameProjectSourceGroup).toHaveBeenCalledWith(
      'one', 'group-1', 'Read later',
    ));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Read later' }));
    await waitFor(() => expect(api.deleteProjectSourceGroup).toHaveBeenCalledWith('one', 'group-1'));
  });
});
