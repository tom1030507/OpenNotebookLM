// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'react-dom';

import api, {
  ApiError,
  type Document,
  type MindMap,
  type Project,
  type VideoSummary,
} from '@/lib/api';
import useStore from '@/store/useStore';
import useNotes from '@/store/useNotes';
import StudioPanel from './StudioPanel';

const projectA: Project = {
  id: 'project-a',
  name: 'Account A project',
  description: null,
  meta_json: {},
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
  role: 'owner',
};

const projectB: Project = {
  ...projectA,
  id: 'project-b',
  name: 'Account B project',
};

const readyDocument: Document = {
  id: 'document-a',
  name: 'Ready source',
  type: 'text',
  isOwnedByCaller: true,
  meta: {},
  status: 'ready',
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
  chunk_count: 1,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

const mindMapFor = (project: Project): MindMap => ({
  project_id: project.id,
  project_name: project.name,
  generated_at: '2026-08-23T00:00:00Z',
  model_used: 'fallback',
  node_count: 1,
  root: {
    id: `root-${project.id}`,
    label: project.name,
    kind: 'project',
    detail: null,
    document_id: null,
    children: [],
  },
});

const videoSummaryFor = (project: Project): VideoSummary => ({
  project_id: project.id,
  project_name: project.name,
  generated_at: '2026-08-23T00:00:00Z',
  model_used: 'fallback',
  scene_count: 1,
  estimated_seconds: 1,
  scenes: [{
    id: `title-${project.id}`,
    kind: 'title',
    headline: project.name,
    bullets: [],
    narration: `A summary of ${project.name}.`,
    document_id: null,
    source_label: null,
  }],
});


beforeEach(() => {
  useStore.setState({
    projects: [projectA, projectB],
    currentProject: projectA,
    documents: [readyDocument],
  });
  useNotes.setState({ projectId: projectA.id, notes: [], loading: false, error: '' });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
  useNotes.setState({ projectId: null, notes: [], loading: false, error: '' });
});

describe('StudioPanel', () => {
  it('uses non-submit controls for every generation action', () => {
    render(<StudioPanel />);

    for (const name of [
      'Audio summary',
      'Video summary',
      'Mind map',
      'Report',
    ]) {
      expect(screen.getByRole('button', { name }).getAttribute('type')).toBe('button');
    }
  });

  it('lets viewers use Studio but hides controls that save results into notes', async () => {
    const viewerProject = { ...projectA, role: 'viewer' as const };
    useStore.setState({ currentProject: viewerProject, projects: [viewerProject] });
    vi.spyOn(api, 'listNotes').mockResolvedValue([]);
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMapFor(viewerProject));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));

    expect(await screen.findByRole('dialog', { name: `${viewerProject.name} mind map` })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Save to notes' })).toBeNull();
  });

  it('explains how to fix a video summary that exceeds the export limits', async () => {
    vi.spyOn(api, 'fetchProjectVideoSummary').mockRejectedValue(
      new ApiError(413, 'Video summary exceeds the PowerPoint export limits'),
    );
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Video summary' }));

    expect(await screen.findByText(/select fewer sources/i)).toBeTruthy();
  });

  it('does not open project A results after switching to project B', async () => {
    const response = deferred<MindMap>();
    vi.spyOn(api, 'fetchProjectMindMap').mockReturnValue(response.promise);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));
    await act(async () => {
      useStore.setState({
        currentProject: projectB,
        documents: [{ ...readyDocument, id: 'document-b' }],
      });
    });
    await act(async () => {
      response.resolve({
        project_id: projectA.id,
        project_name: projectA.name,
        generated_at: '2026-08-23T00:00:00Z',
        model_used: 'fallback',
        node_count: 1,
        root: {
          id: 'root-a',
          label: projectA.name,
          kind: 'project',
          detail: null,
          document_id: null,
          children: [],
        },
      });
      await response.promise;
    });

    expect(screen.queryByRole('dialog', { name: `${projectA.name} mind map` })).toBeNull();
  });

  it('does not render an already-open project A map in project B\'s commit', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMapFor(projectA));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));
    expect(await screen.findByRole('dialog', { name: `${projectA.name} mind map` })).toBeTruthy();

    flushSync(() => {
      useStore.setState({
        currentProject: projectB,
        documents: [{ ...readyDocument, id: 'document-b' }],
      });
    });

    expect(screen.queryByRole('dialog', { name: `${projectA.name} mind map` })).toBeNull();
  });

  it('does not render an already-open project A video in project B\'s commit', async () => {
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(videoSummaryFor(projectA));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Video summary' }));
    expect(await screen.findByRole('dialog', { name: `${projectA.name} video summary` })).toBeTruthy();

    flushSync(() => {
      useStore.setState({
        currentProject: projectB,
        documents: [{ ...readyDocument, id: 'document-b' }],
      });
    });

    expect(screen.queryByRole('dialog', { name: `${projectA.name} video summary` })).toBeNull();
  });

  it('shows the generated report and saves its Markdown to notes', async () => {
    const markdown = '# Project report\n\nSaved findings.';
    vi.spyOn(api, 'listNotes').mockResolvedValue([]);
    vi.spyOn(api, 'exportProjectSummary').mockResolvedValue({
      text: async () => markdown,
    } as Blob);
    const create = vi.spyOn(api, 'createNote').mockResolvedValue({
      id: 'report-note', project_id: projectA.id, title: 'Account A project report',
      content: markdown, origin: 'studio', source_message_id: null,
      studio_kind: 'report', payload_json: null,
      created_at: '2026-10-25T00:00:00Z', updated_at: '2026-10-25T00:00:00Z',
    });
    class TestURL extends URL {}
    TestURL.createObjectURL = vi.fn(() => 'blob:report');
    TestURL.revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', TestURL);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));

    expect(await screen.findByText('Saved findings.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save report to notes' }));

    await waitFor(() => expect(create).toHaveBeenCalledWith(projectA.id, {
      title: 'Account A project report', content: markdown, studio_kind: 'report',
    }));
    expect(useNotes.getState().notes).toHaveLength(1);
  });

  it('saves the displayed mind map payload to notes', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMapFor(projectA));
    vi.spyOn(api, 'createNote').mockResolvedValue({
      id: 'map-note', project_id: projectA.id, title: 'Account A project mind map',
      content: '', origin: 'studio', source_message_id: null,
      studio_kind: 'mindmap', payload_json: mindMapFor(projectA),
      created_at: '2026-10-25T00:00:00Z', updated_at: '2026-10-25T00:00:00Z',
    });
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));
    await screen.findByRole('dialog', { name: `${projectA.name} mind map` });
    fireEvent.click(screen.getByRole('button', { name: 'Save to notes' }));

    await waitFor(() => expect(api.createNote).toHaveBeenCalledWith(projectA.id, {
      title: 'Account A project mind map',
      studio_kind: 'mindmap', payload_json: mindMapFor(projectA),
    }));
    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();
  });
});
