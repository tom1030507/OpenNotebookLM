// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { Project } from '@/lib/api';

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

const initialState = useStore.getState();

beforeEach(() => {
  useStore.setState({ currentProject: project, projects: [project] });
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
  useStore.setState(initialState, true);
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

  it('surfaces a failure without leaving the button stuck', async () => {
    vi.spyOn(api, 'exportProjectSummary').mockRejectedValue(new Error('nope'));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Report' }));

    expect(await screen.findByText(/could not be generated/i)).toBeTruthy();
    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Report' }) as HTMLButtonElement).disabled,
    ).toBe(false));
  });

  it('leaves the outputs without backend support disabled', () => {
    render(<StudioPanel />);

    // Audio has an endpoint but needs the Web Speech API, which jsdom has not.
    for (const name of ['Audio summary', 'Video summary']) {
      const button = screen.getByRole('button', { name: new RegExp(`^${name}`) });
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });
});
