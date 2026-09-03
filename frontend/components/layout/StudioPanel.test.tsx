// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'react-dom';

import api, {
  type Document,
  type MindMap,
  type Project,
  type VideoSummary,
} from '@/lib/api';
import useStore from '@/store/useStore';
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
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
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
});
