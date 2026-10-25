// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'react-dom';
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
  role: 'owner',
};

const source: Document = {
  id: 'doc-1',
  name: 'Example Domain',
  type: 'url',
  isOwnedByCaller: true,
  url: 'https://example.com',
  meta: {},
  status: 'ready',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  chunk_count: 3,
};

const result = {
  markdown: '# Briefing\n\nRainfall increased [Source 1].',
  citations: [{ id: 1, document_id: 'doc-1', source: 'Example Domain', text: 'Rainfall evidence.' }],
};

beforeEach(() => {
  useStore.setState({
    currentProject: project,
    projects: [project],
    documents: [source, { ...source, id: 'doc-2', name: 'Rainfall report' }],
  });
  class TestURL extends URL {}
  TestURL.createObjectURL = vi.fn(() => 'blob:report');
  TestURL.revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', TestURL);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.getState().resetForTests();
});

describe('Studio report', () => {
  it('opens a format picker and displays cited Markdown with a download action', async () => {
    const spy = vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(result);
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));
    expect(await screen.findByRole('dialog', { name: 'Research notes report' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));

    expect(await screen.findByRole('button', { name: 'Preview source 1' })).toBeTruthy();
    expect(spy).toHaveBeenCalledWith('project-1', { format: 'briefing' });
    fireEvent.click(screen.getByRole('button', { name: 'Download Markdown' }));
    expect(downloads).toEqual(['Research notes-report.md']);
  });

  it('reports on the selected sources only', async () => {
    const spy = vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(result);
    useStore.getState().toggleSourceSelected('project-1', 'doc-2');
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));
    await screen.findByRole('dialog', { name: 'Research notes report' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1', {
      format: 'briefing', document_ids: ['doc-1'],
    }));
  });

  it('keeps the report action unavailable with no source selected', () => {
    useStore.getState().setAllSourcesSelected('project-1', false);
    render(<StudioPanel />);

    expect((screen.getByRole('button', { name: 'Report' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps the report action unavailable without a project', () => {
    useStore.setState({ currentProject: null, projects: [] });
    render(<StudioPanel />);

    expect((screen.getByRole('button', { name: /^Report/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('announces report generation and allows the dialog to close', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockReturnValue(new Promise(() => undefined));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));
    await screen.findByRole('dialog', { name: 'Research notes report' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));

    expect(await screen.findByRole('status', { name: 'Generating report' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close report dialog' }));
    expect(screen.queryByRole('dialog', { name: 'Research notes report' })).toBeNull();
  });

  it('surfaces a generation failure inside the dialog', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockRejectedValue(new Error('nope'));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));
    await screen.findByRole('dialog', { name: 'Research notes report' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be generated/i);
  });

  it('does not display a report after switching projects mid-generation', async () => {
    let resolve!: (value: typeof result) => void;
    const pending = new Promise<typeof result>((done) => { resolve = done; });
    vi.spyOn(api, 'fetchProjectReport').mockReturnValue(pending);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));
    await screen.findByRole('dialog', { name: 'Research notes report' });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    flushSync(() => {
      useStore.setState({
        currentProject: { ...project, id: 'project-2', name: 'Other project' },
        documents: [{ ...source, id: 'doc-3' }],
      });
    });
    expect(screen.queryByRole('dialog', { name: 'Research notes report' })).toBeNull();

    await act(async () => {
      resolve({ ...result, markdown: '# Stale report' });
      await pending;
    });
    expect(screen.queryByText('Stale report')).toBeNull();
  });

  it('leaves an output the browser cannot produce disabled', async () => {
    vi.spyOn(api, 'listAudioOverviews').mockResolvedValue({ enabled: false, items: [], voices: [] });
    render(<StudioPanel />);

    const audio = screen.getByRole('button', { name: /^Audio summary/ });
    fireEvent.click(audio);
    await waitFor(() => expect((audio as HTMLButtonElement).disabled).toBe(true));

    for (const name of ['Video summary', 'Mind map', 'Report']) {
      const button = screen.getByRole('button', { name: new RegExp(`^${name}`) });
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
  });
});
