'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api, {
  type AudioOverview,
  type AudioOverviewFormat,
  type AudioOverviewLength,
  type AudioOverviewVoice,
  type StudioOutputOptions,
} from '@/lib/api';

interface AudioOverviewDialogProps {
  projectId: string;
  documentIds?: string[];
  initialOptions?: StudioOutputOptions;
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
  initialOptions,
  onClose,
}: AudioOverviewDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const titleId = useId();
  const [format, setFormat] = useState<AudioOverviewFormat>('deep_dive');
  const [length, setLength] = useState<AudioOverviewLength>(initialOptions?.length ?? 'default');
  const [audience, setAudience] = useState(initialOptions?.audience ?? 'general');
  const [focus, setFocus] = useState(initialOptions?.focus ?? '');
  const [voiceA, setVoiceA] = useState<AudioOverviewVoice>('af_heart');
  const [voiceB, setVoiceB] = useState<AudioOverviewVoice>('am_adam');
  const [voices, setVoices] = useState<AudioOverviewVoice[]>([]);
  const [items, setItems] = useState<AudioOverview[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ host: 'A' | 'B'; url: string } | null>(null);
  const [previewing, setPreviewing] = useState<'A' | 'B' | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  useEffect(() => {
    let active = true;
    api.listAudioOverviews(projectId).then(({ items: saved, voices: availableVoices }) => {
      if (!active) return;
      setItems(saved);
      setVoices(availableVoices);
      setSelectedId(saved[0]?.id ?? null);
    }).catch(() => {
      if (active) setError('Saved audio overviews could not be loaded.');
    }).finally(() => {
      if (active) setIsLoading(false);
    });
    return () => { active = false; };
  }, [projectId]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = playbackRate;
  }, [audioUrl, playbackRate]);

  useEffect(() => {
    if (!preview) return undefined;
    return () => URL.revokeObjectURL(preview.url);
  }, [preview]);

  const selected = items.find((item) => item.id === selectedId) ?? null;
  const selectedStatus = selected?.status;

  const previewVoice = async (host: 'A' | 'B', voice: AudioOverviewVoice) => {
    setPreviewing(host);
    setError('');
    try {
      const sample = await api.fetchAudioOverviewVoicePreview(voice);
      setPreview({ host, url: URL.createObjectURL(sample) });
    } catch {
      setError('The voice preview could not be loaded.');
    } finally {
      setPreviewing(null);
    }
  };

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
        audience,
        focus: focus.trim() || null,
        voice_a: voiceA,
        voice_b: voiceB,
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
            <div className="grid gap-4 sm:grid-cols-3">
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
                  <option value="long">Long</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                Audience
                <select
                  value={audience}
                  onChange={(event) => setAudience(event.target.value as typeof audience)}
                  className="rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
                >
                  <option value="general">General</option>
                  <option value="beginner">Beginner</option>
                  <option value="expert">Expert</option>
                </select>
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {([
                { host: 'A' as const, voice: voiceA, setVoice: setVoiceA },
                { host: 'B' as const, voice: voiceB, setVoice: setVoiceB },
              ]).map(({ host, voice, setVoice }) => (
                <div key={host} className="space-y-1.5 text-sm">
                  <label htmlFor={`audio-overview-voice-${host.toLowerCase()}`}>
                    Host {host} voice
                  </label>
                  <div className="flex gap-2">
                    <select
                      id={`audio-overview-voice-${host.toLowerCase()}`}
                      aria-label={`Host ${host} voice`}
                      value={voice}
                      disabled={previewing !== null}
                      onChange={(event) => {
                        setVoice(event.target.value as AudioOverviewVoice);
                        setPreview(null);
                      }}
                      className="min-w-0 flex-1 rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2"
                    >
                      {voices.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                    <button
                      type="button"
                      aria-label={`Preview Host ${host} voice`}
                      disabled={previewing !== null || voices.length === 0}
                      onClick={() => previewVoice(host, voice)}
                      className="rounded-md border border-[var(--input)] px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-60"
                    >
                      {previewing === host
                        ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        : 'Preview'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-[var(--muted-foreground)]">
              Each voice pack downloads on first use and uses about 523 KB of model cache.
            </p>
            {preview && (
              <audio
                controls
                autoPlay
                preload="auto"
                src={preview.url}
                aria-label={`Host ${preview.host} voice preview`}
              >
                Your browser does not support audio playback.
              </audio>
            )}
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
                <div className="flex flex-wrap items-center gap-3">
                  <audio
                    ref={audioRef}
                    controls
                    preload="metadata"
                    src={audioUrl}
                    aria-label="Audio overview playback"
                  >
                    Your browser does not support audio playback.
                  </audio>
                  <label className="flex items-center gap-2 text-sm">
                    Playback speed
                    <select
                      aria-label="Playback speed"
                      value={playbackRate}
                      onChange={(event) => setPlaybackRate(Number(event.target.value))}
                      className="rounded-md border border-[var(--input)] bg-[var(--card)] px-2 py-1.5"
                    >
                      <option value={0.75}>0.75×</option>
                      <option value={1}>1×</option>
                      <option value={1.25}>1.25×</option>
                      <option value={1.5}>1.5×</option>
                      <option value={2}>2×</option>
                    </select>
                  </label>
                </div>
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
