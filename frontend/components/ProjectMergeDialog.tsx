'use client';

import React, { useId, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import type {
  Project,
  ProjectMergeMode,
  ProjectMergeResponse,
} from '@/lib/api';

interface ProjectMergeDialogProps {
  sourceProject: Project;
  projects: Project[];
  onClose: () => void;
  onMerge: (
    targetProjectId: string,
    mode: ProjectMergeMode,
  ) => Promise<ProjectMergeResponse | null>;
}

export default function ProjectMergeDialog({
  sourceProject,
  projects,
  onClose,
  onMerge,
}: ProjectMergeDialogProps) {
  const [targetProjectId, setTargetProjectId] = useState('');
  const [mode, setMode] = useState<ProjectMergeMode | ''>('');
  const [isMerging, setIsMerging] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ProjectMergeResponse | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const targetRef = useRef<HTMLSelectElement>(null);
  const titleId = useId();
  const targets = projects.filter(
    (project) => project.id !== sourceProject.id && project.role === 'owner',
  );
  const targetProject = projects.find((project) => project.id === result?.target_project_id);

  useDialogFocus({
    isOpen: true,
    onClose,
    dismissible: !isMerging,
    dialogRef,
    initialFocusRef: result ? closeRef : targetRef,
  });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!targetProjectId || !mode || isMerging) return;
    setIsMerging(true);
    setError('');
    try {
      setResult(await onMerge(targetProjectId, mode));
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Failed to merge projects');
    } finally {
      setIsMerging(false);
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
        className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--popover)] shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] p-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold">Merge Project</h2>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              From {sourceProject.name}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close merge project dialog"
            onClick={onClose}
            disabled={isMerging}
            className="rounded-lg p-2 hover:bg-[var(--muted)] disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {result ? (
          <div className="space-y-4 p-4">
            <p role="status" className="text-sm">
              {result.mode === 'move' ? 'Moved' : 'Copied'} {result.sources_merged}{' '}
              {result.sources_merged === 1 ? 'source' : 'sources'}, {result.notes_merged}{' '}
              {result.notes_merged === 1 ? 'note' : 'notes'}, and {result.conversations_merged}{' '}
              {result.conversations_merged === 1 ? 'conversation' : 'conversations'} into{' '}
              {targetProject?.name ?? 'the target project'}.
            </p>
            {result.skipped_sources.length > 0 && (
              <div>
                <p className="text-sm font-medium">Duplicate sources left in the source project:</p>
                <ul className="mt-1 list-inside list-disc text-sm text-[var(--muted-foreground)]">
                  {result.skipped_sources.map((source) => (
                    <li key={source.id}>{source.title}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="h-9 rounded-md bg-[var(--primary)] px-4 text-sm text-[var(--primary-foreground)]"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 p-4">
            {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
            <label className="block text-sm font-medium" htmlFor="merge-target">
              Merge into
            </label>
            <select
              ref={targetRef}
              id="merge-target"
              value={targetProjectId}
              onChange={(event) => setTargetProjectId(event.target.value)}
              disabled={isMerging}
              className="h-10 w-full rounded-md border border-[var(--input)] bg-[var(--background)] px-3 text-sm"
              required
            >
              <option value="">Select a project</option>
              {targets.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
            <label className="block text-sm font-medium" htmlFor="merge-mode">
              Content handling
            </label>
            <select
              id="merge-mode"
              value={mode}
              onChange={(event) => setMode(event.target.value as ProjectMergeMode | '')}
              disabled={isMerging}
              className="h-10 w-full rounded-md border border-[var(--input)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">Select move or copy</option>
              <option value="move">Move content from the source project</option>
              <option value="copy">Copy content and keep the source project</option>
            </select>
            <p className="text-xs text-[var(--muted-foreground)]">
              The source project stays in your project list. Duplicate sources remain there.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={isMerging}
                className="h-9 rounded-md border border-[var(--border)] px-3 text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!targetProjectId || !mode || isMerging || targets.length === 0}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-[var(--primary)] px-4 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
              >
                {isMerging && <Loader2 className="h-4 w-4 animate-spin" />}
                {isMerging ? 'Merging...' : 'Merge project'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
