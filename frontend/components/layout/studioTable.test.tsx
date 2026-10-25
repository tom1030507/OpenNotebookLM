// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { Document, Project, ProjectTable } from '@/lib/api';

const project: Project = {
  id: 'project-1', name: 'Research notes', description: null, meta_json: {},
  created_at: '2026-08-13T00:00:00Z', updated_at: '2026-08-13T00:00:00Z',
  document_count: 1, conversation_count: 0, role: 'owner',
};

const source: Document = {
  id: 'doc-1', name: 'Paper A', type: 'txt', isOwnedByCaller: true,
  meta: {}, status: 'ready', created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z', chunk_count: 1,
};

const table: ProjectTable = {
  columns: ['Paper', 'Year'],
  rows: [[
    { value: 'A study', document_id: 'doc-1', source_id: 1 },
    { value: '2025', document_id: 'doc-1', source_id: 2 },
  ]],
  sources: [
    { id: 1, document_id: 'doc-1', title: 'Paper A', excerpt: 'Title: Paper A.' },
    { id: 2, document_id: 'doc-1', title: 'Paper A', excerpt: 'Published in 2025.' },
  ],
};

beforeEach(() => {
  useStore.setState({ currentProject: project, projects: [project], documents: [source] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});

describe('Studio data table', () => {
  it('offers a data table action for the current project', () => {
    render(<StudioPanel />);

    expect(screen.getByRole('button', { name: 'Data table' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Data table' }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it('generates a selected-source table and links its cells to evidence', async () => {
    const spy = vi.spyOn(api, 'fetchProjectTable').mockResolvedValue(table);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Data table' }));
    expect(await screen.findByRole('dialog', { name: 'Research notes data table' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'One row per paper' },
    });
    fireEvent.change(screen.getByLabelText('Columns (optional)'), {
      target: { value: 'Paper, Year' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate table' }));

    expect(await screen.findByText('A study')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Preview source 1' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Preview source 2' }));
    expect(await screen.findByText('Published in 2025.')).toBeTruthy();
    expect(spy).toHaveBeenCalledWith('project-1', {
      instruction: 'One row per paper',
      columns: ['Paper', 'Year'],
    });
  });

  it('submits only selected sources', async () => {
    const spy = vi.spyOn(api, 'fetchProjectTable').mockResolvedValue(table);
    useStore.setState({ documents: [source, { ...source, id: 'doc-2', name: 'Paper B' }] });
    useStore.getState().toggleSourceSelected('project-1', 'doc-2');
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Data table' }));
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'Compare these papers' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate table' }));

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1', {
      instruction: 'Compare these papers', source_ids: ['doc-1'],
    }));
  });

  it('allows another request after changing inputs during generation', async () => {
    vi.spyOn(api, 'fetchProjectTable').mockReturnValue(new Promise(() => undefined));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Data table' }));
    const instruction = screen.getByLabelText('Instruction');
    fireEvent.change(instruction, { target: { value: 'One row per paper' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate table' }));
    expect(await screen.findByRole('status', { name: 'Generating table' })).toBeTruthy();

    fireEvent.change(instruction, { target: { value: 'Compare datasets' } });

    expect(screen.queryByRole('status', { name: 'Generating table' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Generate table' }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it('downloads CSV with a UTF-8 BOM and formula-safe cells', async () => {
    const formulaTable: ProjectTable = {
      ...table,
      rows: [[
        { value: '=SUM(1,1)', document_id: 'doc-1', source_id: 1 },
        { value: '2025', document_id: 'doc-1', source_id: 2 },
      ]],
    };
    vi.spyOn(api, 'fetchProjectTable').mockResolvedValue(formulaTable);
    const createObjectURL = vi.fn((blob: Blob | MediaSource) => {
      void blob;
      return 'blob:table';
    });
    const revokeObjectURL = vi.fn();
    class TestURL extends URL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    }
    vi.stubGlobal('URL', TestURL);
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Data table' }));
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'One row per paper' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate table' }));
    await screen.findByText('=SUM(1,1)');
    fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }));

    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(blob);
    });
    expect([...new Uint8Array(bytes).slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    const csv = new TextDecoder().decode(new Uint8Array(bytes).slice(3));
    expect(csv).toContain('"\'=SUM(1,1)"');
    expect(downloads).toEqual(['Research notes-table.csv']);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:table');
  });

  it('copies the generated table as Markdown', async () => {
    vi.spyOn(api, 'fetchProjectTable').mockResolvedValue(table);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText },
    });
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Data table' }));
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'One row per paper' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate table' }));
    await screen.findByText('A study');
    fireEvent.click(screen.getByRole('button', { name: 'Copy as Markdown' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      '| Paper | Year |\n| --- | --- |\n| A study | 2025 |',
    ));
  });
});
