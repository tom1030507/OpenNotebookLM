'use client';

import { useCallback, useEffect, useState } from 'react';
import { Loader2, RotateCcw, Trash2 } from 'lucide-react';
import api, { type TrashItem, type TrashResponse } from '@/lib/api';
import useNotes from '@/store/useNotes';
import useStore from '@/store/useStore';
import TopNavInfoDialog from './TopNavInfoDialog';

interface TrashDialogProps {
  onClose: () => void;
}

export default function TrashDialog({ onClose }: TrashDialogProps) {
  const [trash, setTrash] = useState<TrashResponse | null>(null);
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [error, setError] = useState('');

  const loadTrash = useCallback(async () => {
    setError('');
    try {
      setTrash(await api.getTrash());
    } catch {
      setError('Trash could not be loaded. Please try again.');
    }
  }, []);

  useEffect(() => {
    void loadTrash();
  }, [loadTrash]);

  const refreshWorkspace = async (item: TrashItem) => {
    const state = useStore.getState();
    if (item.type === 'project') {
      await state.fetchProjects();
    } else if (item.type === 'source' && state.currentProject) {
      await state.refreshDocuments(state.currentProject.id);
    } else if (
      item.type === 'note'
      && item.project_id
      && useNotes.getState().projectId === item.project_id
    ) {
      await useNotes.getState().load(item.project_id);
    }
  };

  const restore = async (item: TrashItem) => {
    setBusyItemId(item.id);
    setError('');
    try {
      await api.restoreTrashItem(item.type, item.id);
      await refreshWorkspace(item);
      await loadTrash();
    } catch {
      setError('The item could not be restored. Please try again.');
    } finally {
      setBusyItemId(null);
    }
  };

  const deleteForever = async (item: TrashItem) => {
    if (!window.confirm(`Delete "${item.title}" forever? This cannot be undone.`)) return;
    setBusyItemId(item.id);
    setError('');
    try {
      await api.deleteTrashItem(item.type, item.id);
      await refreshWorkspace(item);
      await loadTrash();
    } catch {
      setError('The item could not be deleted. Please try again.');
    } finally {
      setBusyItemId(null);
    }
  };

  return (
    <TopNavInfoDialog title="Trash" onClose={onClose}>
      {trash && (
        <p className="mb-3 text-xs text-[var(--muted-foreground)]">
          Items are permanently deleted after {trash.retention_days} days.
        </p>
      )}
      {error && <p role="alert" className="mb-3 text-sm text-[var(--error)]">{error}</p>}
      {!trash ? (
        error ? (
          <button
            type="button"
            onClick={() => void loadTrash()}
            className="text-sm underline underline-offset-2"
          >
            Try again
          </button>
        ) : (
          <p className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            Loading trash...
          </p>
        )
      ) : trash.items.length === 0 ? (
        <p className="text-sm text-[var(--muted-foreground)]">Trash is empty.</p>
      ) : (
        <ul className="space-y-3">
          {trash.items.map((item) => (
            <li key={`${item.type}:${item.id}`} className="rounded-md border border-[var(--border)] p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="break-words text-sm font-medium">{item.title}</p>
                  <p className="mt-1 text-xs capitalize text-[var(--muted-foreground)]">
                    {item.type}{item.project_name ? ` · ${item.project_name}` : ''}
                  </p>
                  <time
                    dateTime={item.deleted_at}
                    className="mt-1 block text-xs text-[var(--muted-foreground)]"
                  >
                    Deleted {new Date(item.deleted_at).toLocaleDateString()}
                  </time>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    aria-label={`Restore ${item.title}`}
                    disabled={busyItemId !== null}
                    onClick={() => void restore(item)}
                    className="rounded-md p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    {busyItemId === item.id
                      ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                      : <RotateCcw aria-hidden="true" className="h-4 w-4" />}
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${item.title} forever`}
                    disabled={busyItemId !== null}
                    onClick={() => void deleteForever(item)}
                    className="rounded-md p-2 text-[var(--error)] hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    <Trash2 aria-hidden="true" className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </TopNavInfoDialog>
  );
}
