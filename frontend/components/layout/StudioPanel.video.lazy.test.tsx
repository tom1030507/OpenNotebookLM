// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const lazyVideoModule = vi.hoisted(() => {
  let resolve!: (module: unknown) => void;
  const promise = new Promise<unknown>((resolveModule) => {
    resolve = resolveModule;
  });

  return { promise, resolve };
});

vi.mock('@/components/VideoSummaryDialog', () => lazyVideoModule.promise);

import api, { type Document, type Project, type VideoSummary } from '@/lib/api';
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

const videoSummary: VideoSummary = {
  project_id: project.id,
  project_name: project.name,
  generated_at: '2026-08-23T00:00:00Z',
  model_used: 'fallback',
  scene_count: 1,
  estimated_seconds: 1,
  scenes: [{
    id: 'title',
    kind: 'title',
    headline: project.name,
    bullets: [],
    narration: 'A summary of the project.',
    document_id: null,
    source_label: null,
  }],
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

describe('StudioPanel video lazy dialog', () => {
  it('announces the pending video dialog chunk and disables a duplicate video operation', async () => {
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(videoSummary);
    render(<StudioPanel />);

    const videoButton = screen.getByRole('button', { name: 'Video summary' });
    fireEvent.click(videoButton);

    expect(await screen.findByRole('status', { name: 'Loading studio result' })).toBeTruthy();
    expect((videoButton as HTMLButtonElement).disabled).toBe(true);
  });
});
