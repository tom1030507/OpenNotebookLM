// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import GitRepositoryDialog from './GitRepositoryDialog';
import api, { type GitRepository, type GitRepositoryOperation } from '@/lib/api';

const repository: GitRepository = {
  id: 'repo-1',
  url: 'https://github.com/org/repo.git',
  include_glob: '**/*.md',
  exclude_glob: '',
  head_commit: 'abcdef012345',
  last_synced_at: '2026-10-26T00:00:00Z',
  file_count: 3,
};

const operation: GitRepositoryOperation = {
  repository,
  added: 1,
  updated: 0,
  unchanged: 2,
  removed: 0,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('GitRepositoryDialog', () => {
  it('imports a repository and clears the one-time token', async () => {
    const getRepositories = vi.spyOn(api, 'getGitRepositories')
      .mockResolvedValueOnce({ repositories: [] })
      .mockResolvedValueOnce({ repositories: [repository] });
    const importRepository = vi.spyOn(api, 'importGitRepository')
      .mockResolvedValue(operation);
    const onSourcesChanged = vi.fn();

    render(
      <GitRepositoryDialog
        projectId="project-1"
        onClose={() => undefined}
        onSourcesChanged={onSourcesChanged}
      />,
    );

    await screen.findByText('No repositories connected.');
    fireEvent.change(screen.getByLabelText('HTTPS repository URL'), {
      target: { value: repository.url },
    });
    fireEvent.change(screen.getByLabelText('Access token (optional; not saved)'), {
      target: { value: 'one-time-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import repository' }));

    expect((await screen.findByRole('status')).textContent)
      .toBe('Added 1, updated 0, unchanged 2, removed 0.');
    expect(importRepository).toHaveBeenCalledWith('project-1', {
      url: repository.url,
      include_glob: '**/*',
      exclude_glob: '',
      token: 'one-time-token',
    });
    expect((screen.getByLabelText('Access token (optional; not saved)') as HTMLInputElement).value)
      .toBe('');
    expect(getRepositories).toHaveBeenCalledTimes(2);
    expect(onSourcesChanged).toHaveBeenCalledOnce();
  });

  it('clears the one-time token after a failed sync', async () => {
    vi.spyOn(api, 'getGitRepositories').mockResolvedValue({ repositories: [repository] });
    const syncRepository = vi.spyOn(api, 'syncGitRepository')
      .mockRejectedValue(new Error('Git access was denied'));

    render(
      <GitRepositoryDialog
        projectId="project-1"
        onClose={() => undefined}
        onSourcesChanged={() => undefined}
      />,
    );

    await screen.findByText(repository.url);
    fireEvent.change(screen.getByLabelText('Access token (optional; not saved)'), {
      target: { value: 'private-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sync' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Git access was denied');
    expect(syncRepository).toHaveBeenCalledWith('project-1', repository.id, 'private-token');
    expect((screen.getByLabelText('Access token (optional; not saved)') as HTMLInputElement).value)
      .toBe('');
  });
});
