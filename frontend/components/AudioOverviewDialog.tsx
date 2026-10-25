'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api, { type AudioOverview, type AudioOverviewFormat, type AudioOverviewLength } from '@/lib/api';

interface AudioOverviewDialogProps {
  projectId: string;
  documentIds?: string[];
  onClose: () => void;
}

const statusLabel: Record<AudioOverview['status'], string> = {
  queued: 'Queued for generation',
  running: 'Generating audio…',
  ready: 'Audio overview ready',
  failed: 'Audio overview failed',
};

export default function AudioOverviewDialog({
  projectId,
  documentIds,
  onClose,
}: AudioOverviewDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const [format, setFormat] = useState<AudioOverviewFormat>('deep_dive');
  const [length, setLength] = useState<AudioOverviewLength>('default');
  const [focus, setFocus] = useState('');
  const [items, setItems] = useState<AudioOverview[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  useEffect(() => {
    let active = true;
    api.listAudioOverviews(projectId).then(({ items: saved }) => {
      if (!active) return;
      setItems(saved);
      setSelectedId(saved[0]?.id ?? null);
    }).catch(() => {
      if (active) setError('Saved audio overviews could not be loaded.');
    }).finally(() => {
      if (active) setIsLoading(false);
    });
    return () => { active = false; };
  }, [projectId]);

  const selected = items.find((item) => item.id === selectedId) ?? null;
  const selectedStatus = selected?.status;

  useEffect(() => {
    if (!selectedId || (selectedStatus !== 'queued' && selectedStatus !== 'running')) {
      return undefined;
    }

    let active = true;
    const timer = window.setInterval(() => {
      api.getAudioOverview(projectId, selectedId).then((updated) => {
        if (!active) return;
        setItems((saved) => saved.map((item) => item.id === updated.id ? updated : item));
      }).catch(() => {
        if (active) setError('Audio generation status could not be refreshed.');
      });
    }, 1500);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [projectId, selectedId, selectedStatus]);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setAudioUrl(null);
    if (selected?.status === 'ready') {
      api.fetchAudioOverviewFile(projectId, selected.id).then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      }).catch(() => {
        if (active) setError('The generated audio could not be loaded.');
      });
    }
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId, selected?.id, selected?.status]);

  const generate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError('');
    try {
      const overview = await api.createAudioOverview(projectId, {
        format,
        length,
        focus: focus.trim() || null,
        ...(documentIds ? { document_ids: documentIds } : {}),
      });
      setItems((saved) => [overview, ...saved.filter((item) => item.id !== overview.id)]);
      setSelectedId(overview.id);
    } catch {
      setError('The audio overview could not be queued. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const dialog = (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg border border-[var(--border)] bg-[var(--popover)] shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">Audio summary</h2>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              Two-host audio generated from this project’s sources.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close audio summary dialog"
            className="rounded-lg p-2 hover:bg-[var(--muted)]"
          >
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <form onSubmit={generate} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                Format
                <select
                  value={format}
                  onChange={(event) => setFormat(event.target.value as AudioOverviewFormat)}
                  className="rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
                >
                  <option value="deep_dive">Deep dive</option>
                  <option value="brief">Brief</option>
                  <option value="critique">Critique</option>
                  <option value="debate">Debate</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                Length
                <select
                  value={length}
                  onChange={(event) => setLength(event.target.value as AudioOverviewLength)}
                  className="rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
                >
                  <option value="short">Short</option>
                  <option value="default">Default</option>
                </select>
              </label>
            </div>
            <label className="flex flex-col gap-1.5 text-sm">
              Focus (optional)
              <textarea
                value={focus}
                onChange={(event) => setFocus(event.target.value)}
                maxLength={500}
                rows={2}
                placeholder="A question or topic for the hosts to focus on"
                className="resize-y rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
              />
            </label>
            <button
              type="submit"
              disabled={isSubmitting || isLoading}
              className="inline-flex items-center gap-2 rounded-md bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:bg-[var(--primary-hover)] disabled:opacity-60"
            >
              {isSubmitting && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />}
              Generate audio summary
            </button>
          </form>

          {items.length > 0 && (
            <label className="flex flex-col gap-1.5 text-sm">
              Saved audio overviews
              <select
                aria-label="Saved audio overview"
                value={selectedId ?? ''}
                onChange={(event) => setSelectedId(event.target.value)}
                className="rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
              >
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {new Date(item.created_at).toLocaleString()} · {item.options.format} · {item.status}
                  </option>
                ))}
              </select>
            </label>
          )}

          {isLoading && <p role="status">Loading saved audio overviews…</p>}
          {selected && (
            <section aria-label="Audio overview result" className="space-y-3 border-t border-[var(--border)] pt-4">
              <p role="status" className="flex items-center gap-2 text-sm">
                {['queued', 'running'].includes(selected.status) && (
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                )}
                {statusLabel[selected.status]}
              </p>
              {selected.status === 'ready' && audioUrl && (
                <audio controls preload="metadata" src={audioUrl} aria-label="Audio overview playback">
                  Your browser does not support audio playback.
                </audio>
              )}
              {selected.status === 'ready' && !audioUrl && (
                <p role="status" className="text-sm text-[var(--muted-foreground)]">Loading audio…</p>
              )}
              {selected.status === 'failed' && (
                <p className="text-sm text-[var(--error)]">
                  {selected.error || 'The audio overview could not be generated.'}
                </p>
              )}
              {selected.script.length > 0 && (
                <ol aria-label="Audio transcript" className="space-y-3">
                  {selected.script.map((turn, index) => (
                    <li key={`${selected.id}-${index}`} className="rounded-md border border-[var(--border)] bg-[var(--card)] p-3 text-sm">
                      <span className="font-medium">Host {turn.speaker}</span>
                      <p className="mt-1 whitespace-pre-wrap">{turn.text}</p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
          {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
