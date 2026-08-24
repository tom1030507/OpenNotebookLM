// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const lazyMindMapModule = vi.hoisted(() => {
  let resolve!: (module: unknown) => void;
  const promise = new Promise<unknown>((resolveModule) => {
    resolve = resolveModule;
  });

  return { promise, resolve };
});

vi.mock('@/components/MindMapDialog', () => lazyMindMapModule.promise);

import api, { type Document, type MindMap, type Project } from '@/lib/api';
import useStore from '@/store/useStore';
import StudioPanel from './StudioPanel';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
};

const readyDocument: Document = {
  id: 'document-1',
  name: 'Ready source',
  type: 'text',
  meta: {},
  status: 'ready',
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
  chunk_count: 1,
};

const mindMap: MindMap = {
  project_id: project.id,
  project_name: project.name,
  generated_at: '2026-08-23T00:00:00Z',
  model_used: 'fallback',
  node_count: 1,
  root: {
    id: 'root',
    label: project.name,
    kind: 'project',
    detail: null,
    document_id: null,
    children: [],
  },
};

beforeEach(() => {
  useStore.getState().resetForTests();
  useStore.setState({
    currentProject: project,
    projects: [project],
    documents: [readyDocument],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});

describe('StudioPanel lazy dialogs', () => {
  it('announces the pending dialog chunk and disables a duplicate mind-map operation', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap);
    render(<StudioPanel />);

    const mindMapButton = screen.getByRole('button', { name: 'Mind map' });
    fireEvent.click(mindMapButton);

    expect(await screen.findByRole('status', { name: 'Loading studio result' })).toBeTruthy();
    expect((mindMapButton as HTMLButtonElement).disabled).toBe(true);
  });
});
