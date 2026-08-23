// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api, { type Document, type MindMap, type Project } from '@/lib/api';
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

const initialState = useStore.getState();

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
  useStore.setState(initialState, true);
});

describe('StudioPanel', () => {
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
});
