// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { MindMap, Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-20T00:00:00Z',
  updated_at: '2026-08-20T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
};

const mindMap = (modelUsed = 'test-model'): MindMap => ({
  project_id: 'project-1',
  project_name: 'Research notes',
  generated_at: '2026-08-20T00:00:00Z',
  model_used: modelUsed,
  node_count: 4,
  root: {
    id: 'root',
    label: 'Research notes',
    kind: 'project',
    detail: null,
    document_id: null,
    children: [
      {
        id: 'doc-1',
        label: 'Only source',
        kind: 'document',
        detail: 'url',
        document_id: 'doc-1',
        children: [
          {
            id: 'doc-1-topic-0',
            label: 'Rainfall',
            kind: 'topic',
            detail: null,
            document_id: 'doc-1',
            children: [],
          },
          {
            id: 'doc-1-topic-1',
            label: 'Glaciers',
            kind: 'topic',
            detail: null,
            document_id: 'doc-1',
            children: [],
          },
        ],
      },
    ],
  },
});

const initialState = useStore.getState();

const openMindMap = async () => {
  render(<StudioPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));
  return screen.findByRole('dialog');
};

beforeEach(() => {
  useStore.setState({ currentProject: project, projects: [project] });
  class TestURL extends URL {}
  TestURL.createObjectURL = vi.fn(() => 'blob:mindmap');
  TestURL.revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', TestURL);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.setState(initialState, true);
});

describe('Studio mind map', () => {
  it('opens the map of the selected project', async () => {
    const spy = vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());

    await openMindMap();

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1'));
    expect(screen.getByText('Research notes mind map')).toBeTruthy();
  });

  it('draws a node for every source and topic', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());

    await openMindMap();

    expect(await screen.findByText('Only source')).toBeTruthy();
    expect(screen.getByText('Rainfall')).toBeTruthy();
    expect(screen.getByText('Glaciers')).toBeTruthy();
  });

  it('collapses a branch so a large map stays readable', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());

    await openMindMap();
    const branch = await screen.findByRole('button', { name: /Only source/ });
    expect(branch.getAttribute('aria-expanded')).toBe('true');

    fireEvent.click(branch);

    expect(screen.queryByText('Rainfall')).toBeNull();
    expect(
      screen.getByRole('button', { name: /Only source/ }).getAttribute('aria-expanded'),
    ).toBe('false');
  });

  it('says when the topics came from document structure rather than a model', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap('fallback'));

    await openMindMap();

    expect(await screen.findByText(/document structure/i)).toBeTruthy();
    expect(screen.queryByText(/fallback/i)).toBeNull();
  });

  it('names the model that produced the topics', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap('claude-opus'));

    await openMindMap();

    expect(await screen.findByText(/claude-opus/)).toBeTruthy();
  });

  it('downloads the map as Markdown', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());
    const downloads: string[] = [];
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag) as HTMLElement;
      if (tag === 'a') {
        (el as HTMLAnchorElement).click = () =>
          downloads.push((el as HTMLAnchorElement).download);
      }
      return el;
    });

    await openMindMap();
    fireEvent.click(await screen.findByRole('button', { name: /download/i }));

    await waitFor(() => expect(downloads).toEqual(['Research notes mind map.md']));
  });

  it('closes without leaving the action stuck', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());

    await openMindMap();
    fireEvent.click(await screen.findByRole('button', { name: /close/i }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(
      (screen.getByRole('button', { name: 'Mind map' }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it('renders the dialog outside the Studio panel', async () => {
    // The mobile Studio drawer slides in with a transform, which makes it the
    // containing block for `position: fixed`. A dialog rendered inside it is
    // trapped at the drawer's width instead of covering the screen.
    vi.spyOn(api, 'fetchProjectMindMap').mockResolvedValue(mindMap());

    const dialog = await openMindMap();

    expect(dialog.closest('aside')).toBeNull();
  });

  it('keeps the action unavailable without a project', () => {
    useStore.setState({ currentProject: null, projects: [] });
    render(<StudioPanel />);

    expect(
      (screen.getByRole('button', { name: /^Mind map/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('surfaces a failure instead of opening an empty map', async () => {
    vi.spyOn(api, 'fetchProjectMindMap').mockRejectedValue(new Error('nope'));

    render(<StudioPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Mind map' }));

    expect(await screen.findByText(/mind map could not be built/i)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Mind map' }) as HTMLButtonElement).disabled,
    ).toBe(false));
  });
});
