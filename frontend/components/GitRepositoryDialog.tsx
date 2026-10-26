'use client';

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api, { type GitRepository, type GitRepositoryOperation } from '@/lib/api';

interface GitRepositoryDialogProps {
  projectId: string;
  onClose: () => void;
  onSourcesChanged: () => void;
}

const resultMessage = (operation: GitRepositoryOperation) => (
  `Added ${operation.added}, updated ${operation.updated}, `
  + `unchanged ${operation.unchanged}, removed ${operation.removed}.`
);

export default function GitRepositoryDialog({
  projectId,
  onClose,
  onSourcesChanged,
}: GitRepositoryDialogProps) {
  const [repositories, setRepositories] = useState<GitRepository[]>([]);
  const [url, setUrl] = useState('');
  const [includeGlob, setIncludeGlob] = useState('**/*');
  const [excludeGlob, setExcludeGlob] = useState('');
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useDialogFocus({
    isOpen: true,
    onClose,
    dismissible: !busy,
    dialogRef,
    initialFocusRef: closeRef,
  });

  const reloadRepositories = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.getGitRepositories(projectId);
      setRepositories(response.repositories);
      setError('');
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Could not load repositories');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void reloadRepositories();
  }, [reloadRepositories]);

  const handleImport = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!url.trim() || busy) return;
    const requestToken = token.trim() || undefined;
    setToken('');
    setBusy('import');
    setError('');
    setStatus('');
    try {
      const operation = await api.importGitRepository(projectId, {
        url: url.trim(),
        include_glob: includeGlob.trim() || '**/*',
        exclude_glob: excludeGlob.trim(),
        ...(requestToken ? { token: requestToken } : {}),
      });
      setStatus(resultMessage(operation));
      onSourcesChanged();
      await reloadRepositories();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Could not import repository');
    } finally {
      setToken('');
      setBusy(null);
    }
  };

  const handleSync = async (repository: GitRepository) => {
    if (busy) return;
    const requestToken = token.trim() || undefined;
    setToken('');
    setBusy(repository.id);
    setError('');
    setStatus('');
    try {
      const operation = await api.syncGitRepository(
        projectId,
        repository.id,
        requestToken,
      );
      setStatus(resultMessage(operation));
      onSourcesChanged();
      await reloadRepositories();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Could not sync repository');
    } finally {
      setToken('');
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-3">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--popover)] shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] p-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold">Git repositories</h2>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              Import Markdown, text, and code files. Re-sync to fetch new commits.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close Git repositories dialog"
            onClick={onClose}
            disabled={Boolean(busy)}
            className="rounded-lg p-2 hover:bg-[var(--muted)] disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <form onSubmit={(event) => void handleImport(event)} className="space-y-3">
            <label className="block text-xs" htmlFor="git-repository-url">HTTPS repository URL</label>
            <input
              id="git-repository-url"
              type="url"
              required
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/org/repository.git"
              disabled={Boolean(busy)}
              className="h-9 w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-2 text-sm"
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs" htmlFor="git-include-glob">Include glob</label>
                <input
                  id="git-include-glob"
                  value={includeGlob}
                  onChange={(event) => setIncludeGlob(event.target.value)}
                  disabled={Boolean(busy)}
                  className="mt-1 h-9 w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs" htmlFor="git-exclude-glob">Exclude glob</label>
                <input
                  id="git-exclude-glob"
                  value={excludeGlob}
                  onChange={(event) => setExcludeGlob(event.target.value)}
                  disabled={Boolean(busy)}
                  className="mt-1 h-9 w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-2 text-sm"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs" htmlFor="git-access-token">
                Access token (optional; not saved)
              </label>
              <input
                id="git-access-token"
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                disabled={Boolean(busy)}
                className="mt-1 h-9 w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-2 text-sm"
              />
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                Private repository tokens are sent only for the import or sync you start.
              </p>
            </div>
            <button
              type="submit"
              disabled={Boolean(busy) || !url.trim()}
              className="flex h-9 items-center gap-2 rounded-md bg-[var(--primary)] px-3 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {busy === 'import' && <Loader2 className="h-4 w-4 animate-spin" />}
              Import repository
            </button>
          </form>

          <section aria-labelledby={`${titleId}-saved`} className="border-t border-[var(--border)] pt-4">
            <h3 id={`${titleId}-saved`} className="text-sm font-medium">Saved repositories</h3>
            {loading ? (
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">Loading repositories…</p>
            ) : repositories.length ? (
              <ul className="mt-2 space-y-2">
                {repositories.map((repository) => (
                  <li key={repository.id} className="flex items-center gap-2 rounded-md bg-[var(--muted)] p-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs" title={repository.url}>{repository.url}</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        {repository.file_count} files · {repository.head_commit?.slice(0, 8) ?? 'not synced'}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleSync(repository)}
                      disabled={Boolean(busy)}
                      className="flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-xs hover:bg-[var(--card)] disabled:opacity-50"
                    >
                      {busy === repository.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                      Sync
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">No repositories connected.</p>
            )}
          </section>

          {status && <p role="status" className="text-xs">{status}</p>}
          {error && <p role="alert" className="text-xs text-[var(--error)]">{error}</p>}
        </div>
      </div>
    </div>
  );
}
