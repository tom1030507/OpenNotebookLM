// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { Document, Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 2,
  conversation_count: 1,
};

const source: Document = {
  id: 'doc-1',
  name: 'Example Domain',
  type: 'url',
  url: 'https://example.com',
  meta: {},
  status: 'ready',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  chunk_count: 3,
};


beforeEach(() => {
  useStore.setState({
    currentProject: project,
    projects: [project],
    // The project has two sources, so the list the panel reads holds two.
    documents: [source, { ...source, id: 'doc-2', name: 'Rainfall report' }],
  });
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:report'),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.getState().resetForTests();
});

describe('Studio report', () => {
  it('downloads a project summary when a project is selected', async () => {
    const blob = new Blob(['# Summary'], { type: 'text/markdown' });
    const spy = vi.spyOn(api, 'exportProjectSummary').mockResolvedValue(blob);
    const clicks: string[] = [];
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag) as HTMLElement;
      if (tag === 'a') {
        (el as HTMLAnchorElement).click = () => clicks.push((el as HTMLAnchorElement).download);
      }
      return el;
    });

    render(<StudioPanel />);

    const report = screen.getByRole('button', { name: 'Report' });
    expect((report as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(report);

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1'));
    await waitFor(() => expect(clicks.length).toBe(1));
    expect(clicks[0]).toMatch(/Research notes/);
  });

  it('keeps the report action unavailable without a project', () => {
    useStore.setState({ currentProject: null, projects: [] });
    render(<StudioPanel />);

    expect((screen.getByRole('button', { name: /^Report/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('announces while the report is being generated', async () => {
    vi.spyOn(api, 'exportProjectSummary').mockReturnValue(new Promise(() => undefined));
    render(<StudioPanel />);

    const report = screen.getByRole('button', { name: 'Report' });
    fireEvent.click(report);

    await waitFor(() => expect(report.getAttribute('title')).toBe('Generating report…'));
    const hintId = report.getAttribute('aria-describedby');
    expect(hintId && document.getElementById(hintId)?.textContent).toBe('Generating report…');
  });

  it('surfaces a failure without leaving the button stuck', async () => {
    vi.spyOn(api, 'exportProjectSummary').mockRejectedValue(new Error('nope'));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));

    expect(await screen.findByText(/could not be generated/i)).toBeTruthy();
    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Report' }) as HTMLButtonElement).disabled,
    ).toBe(false));
  });

  it('leaves an output the browser cannot produce disabled', () => {
    render(<StudioPanel />);

    // Audio has an endpoint but needs the Web Speech API, which jsdom has not.
    // Every other output is produced by the backend, so every other output is
    // usable here.
    expect((screen.getByRole('button', {
      name: /^Audio summary/,
    }) as HTMLButtonElement).disabled).toBe(true);

    for (const name of ['Video summary', 'Mind map', 'Report']) {
      const button = screen.getByRole('button', { name: new RegExp(`^${name}`) });
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
  });
});
