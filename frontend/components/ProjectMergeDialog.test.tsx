// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ProjectMergeDialog from './ProjectMergeDialog';
import type { Project, ProjectMergeResponse } from '@/lib/api';

const project = (id: string, role: Project['role'] = 'owner'): Project => ({
  id,
  name: `Project ${id}`,
  description: null,
  meta_json: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
  role,
});

describe('ProjectMergeDialog', () => {
  afterEach(cleanup);

  it('merges into an owned target with the chosen mode and reports skipped sources', async () => {
    const response: ProjectMergeResponse = {
      target_project_id: 'target',
      mode: 'copy',
      sources_merged: 1,
      notes_merged: 2,
      conversations_merged: 1,
      skipped_sources: [{ id: 'duplicate', title: 'Already in target' }],
    };
    const onMerge = vi.fn().mockResolvedValue(response);
    const source = project('source');

    render(
      <ProjectMergeDialog
        sourceProject={source}
        projects={[source, project('target'), project('shared', 'viewer')]}
        onClose={() => undefined}
        onMerge={onMerge}
      />,
    );

    const target = screen.getByRole('combobox', { name: 'Merge into' });
    expect((target as HTMLSelectElement).querySelectorAll('option')).toHaveLength(2);
    fireEvent.change(target, { target: { value: 'target' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Content handling' }), {
      target: { value: 'copy' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Merge project' }));

    expect((await screen.findByRole('status')).textContent).toContain('Copied 1 source');
    expect(screen.getByText('Already in target')).toBeTruthy();
    expect(onMerge).toHaveBeenCalledWith('target', 'copy');
  });

  it('shows a failed merge without closing the dialog', async () => {
    const onMerge = vi.fn().mockRejectedValue(new Error('Merge request failed'));
    const source = project('source');

    render(
      <ProjectMergeDialog
        sourceProject={source}
        projects={[source, project('target')]}
        onClose={() => undefined}
        onMerge={onMerge}
      />,
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'Merge into' }), {
      target: { value: 'target' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Content handling' }), {
      target: { value: 'move' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Merge project' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Merge request failed');
    expect(screen.getByRole('dialog', { name: 'Merge Project' })).toBeTruthy();
  });
});
