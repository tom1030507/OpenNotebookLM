'use client';

import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Download,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  VolumeX,
  X,
} from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import type { VideoSummary } from '@/lib/api';
import { isSpeechSupported, speakText, stopSpeaking } from '@/lib/speech';
import {
  FALLBACK_MODEL,
  elapsedSeconds,
  formatClock,
  sceneSeconds,
  sceneTimeline,
  totalSeconds,
  videoSummaryToMarkdown,
} from './videoSummaryTiming';

interface VideoSummaryDialogProps {
  summary: VideoSummary;
  onClose: () => void;
}

/** How often the progress bar catches up with the clock, in milliseconds. */
const PROGRESS_TICK_MS = 250;

/**
 * Studio's video summary, played as a narrated slideshow.
 *
 * Playback is driven by the voice, not by a timer: each scene's narration is one
 * `speakText` call, and the scene advances when that call settles. A timer would
 * drift against the listener's own speech rate within a few scenes, leaving the
 * slide describing something the narrator had already moved past.
 *
 * Where the browser has no speech synthesis, or where it breaks mid-playback,
 * the same slides run on a timer instead and the player says the narration is
 * silent — a silent slideshow is still the summary; a stalled one is not.
 */
export default function VideoSummaryDialog({
  summary,
  onClose,
}: VideoSummaryDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  const scenes = summary.scenes;
  const timeline = useMemo(() => sceneTimeline(scenes), [scenes]);
  const total = useMemo(() => totalSeconds(timeline), [timeline]);

  const [index, setIndex] = useState(0);
  // A video plays. The dialog is only ever opened by a click, which is the
  // gesture browsers require before speaking.
  const [isPlaying, setIsPlaying] = useState(scenes.length > 0);
  const [withinScene, setWithinScene] = useState(0);
  const [narrating, setNarrating] = useState(() => isSpeechSupported());
  const [narrationFailed, setNarrationFailed] = useState(false);

  // Identifies the playback in progress. Anything that ends it retires the run,
  // so a promise or timer that settles afterwards cannot advance a scene the
  // listener has since moved away from — `speakText` resolves when cancelled,
  // which would otherwise turn every pause into a skip.
  const run = useRef(0);

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  const scene = scenes[index];

  useEffect(() => {
    if (!isPlaying || !scene) return undefined;

    const current = run.current + 1;
    run.current = current;
    const isCurrent = () => run.current === current;

    setWithinScene(0);
    const startedAt = Date.now();
    const ticker = window.setInterval(() => {
      if (isCurrent()) setWithinScene((Date.now() - startedAt) / 1000);
    }, PROGRESS_TICK_MS);

    const advance = () => {
      if (!isCurrent()) return;

      if (index < scenes.length - 1) setIndex(index + 1);
      else setIsPlaying(false);
    };

    let timer = 0;
    if (narrating) {
      speakText(scene.narration).then(advance).catch(() => {
        if (!isCurrent()) return;

        // Keep the slides moving without the voice rather than stopping dead.
        setNarrating(false);
        setNarrationFailed(true);
      });
    } else {
      timer = window.setTimeout(advance, sceneSeconds(scene) * 1000);
    }

    return () => {
      // Retire this run before tearing it down, so the cancellation that
      // `stopSpeaking` reports cannot be mistaken for the scene finishing.
      run.current += 1;
      window.clearInterval(ticker);
      if (timer) window.clearTimeout(timer);
      stopSpeaking();
    };
  }, [index, isPlaying, narrating, scene, scenes.length]);

  // Stop the voice when the dialog goes away, however it goes away.
  useEffect(() => () => {
    run.current += 1;
    stopSpeaking();
  }, []);

  const goTo = (next: number) => {
    setIndex(Math.min(Math.max(0, next), Math.max(0, scenes.length - 1)));
    setWithinScene(0);
  };

  const title = `${summary.project_name} video summary`;
  // Not "no model was used": the API reports the fallback both when no provider
  // is configured and when one answered with something unusable, and claiming
  // the second case never called a model would be false.
  const provenance = summary.model_used === FALLBACK_MODEL
    ? 'Narration taken from document structure rather than from a language model.'
    : `Narration written by ${summary.model_used}.`;

  const elapsed = elapsedSeconds(timeline, index, withinScene);
  const progress = total > 0 ? Math.min(100, (elapsed / total) * 100) : 0;

  const download = () => {
    const blob = new Blob([videoSummaryToMarkdown(summary)], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${title}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Portalled to the body rather than left inside the Studio panel. The mobile
  // Studio drawer slides in with a transform, and a transformed ancestor becomes
  // the containing block for `position: fixed` — which would pin this dialog to
  // the drawer's 320px width instead of the screen.
  return createPortal(
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--background)] rounded-lg w-full max-w-3xl max-h-[85vh] flex flex-col"
      >
        <div className="flex items-start justify-between gap-3 p-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            {/* The name truncates on a narrow screen, so keep it reachable. */}
            <h2 id={titleId} title={title} className="text-lg font-semibold truncate">
              {title}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">{provenance}</p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={download}
              aria-label="Download video summary script"
              title="Download video summary script"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              aria-label="Close video summary dialog"
              title="Close video summary dialog"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {!scene ? (
          <div className="p-6">
            <p className="text-sm text-[var(--muted-foreground)]">
              This project has no sources yet, so there is nothing to summarise.
              Add a source and try again.
            </p>
          </div>
        ) : (
          <>
            {/* The slide. Announced politely so a screen reader hears each
                scene, and the narration is on screen as well as spoken so the
                summary is complete without any audio at all. */}
            <div
              aria-live="polite"
              aria-atomic="true"
              className="flex-1 min-h-0 overflow-y-auto p-6"
            >
              <div key={scene.id} className="scene-in">
                <p className="text-xs uppercase tracking-wide text-[var(--muted-foreground)]">
                  {`Scene ${index + 1} of ${scenes.length}`}
                </p>
                <h3 className="mt-2 text-2xl font-semibold leading-snug">
                  {scene.headline}
                </h3>

                {scene.bullets.length > 0 && (
                  <ul className="mt-4 space-y-2">
                    {scene.bullets.map((bullet) => (
                      <li key={bullet} className="flex gap-2 text-sm">
                        <span
                          aria-hidden="true"
                          className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[var(--accent)] shrink-0"
                        />
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {scene.source_label && (
                  <p className="mt-4 text-xs text-[var(--muted-foreground)]">
                    {`Source: ${scene.source_label}`}
                  </p>
                )}

                <p className="mt-5 pt-4 border-t border-[var(--border)] text-sm text-[var(--muted-foreground)]">
                  {scene.narration}
                </p>
              </div>
            </div>

            <div className="p-4 border-t border-[var(--border)]">
              {!narrating && (
                <p className="mb-3 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                  <VolumeX aria-hidden="true" className="w-3.5 h-3.5 shrink-0" />
                  <span>
                    {narrationFailed
                      ? 'Narration stopped, so the slides are playing without it.'
                      : 'This browser cannot read the narration out, so the slides play silently.'}
                  </span>
                </p>
              )}

              <div
                role="progressbar"
                aria-label="Video summary progress"
                aria-valuemin={0}
                aria-valuemax={Math.round(total)}
                aria-valuenow={Math.round(elapsed)}
                className="h-1.5 w-full rounded-full bg-[var(--secondary)] overflow-hidden"
              >
                <div
                  className="h-full bg-[var(--accent)] transition-base"
                  style={{ width: `${progress}%` }}
                />
              </div>

              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => goTo(index - 1)}
                  disabled={index === 0}
                  aria-label="Previous scene"
                  title="Previous scene"
                  className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <SkipBack className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setIsPlaying((playing) => !playing)}
                  aria-label={isPlaying ? 'Pause video summary' : 'Play video summary'}
                  title={isPlaying ? 'Pause video summary' : 'Play video summary'}
                  className="p-2.5 rounded-lg bg-[var(--accent)] text-white transition-base"
                >
                  {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                </button>
                <button
                  type="button"
                  onClick={() => goTo(index + 1)}
                  disabled={index >= scenes.length - 1}
                  aria-label="Next scene"
                  title="Next scene"
                  className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <SkipForward className="w-4 h-4" />
                </button>
                <p className="ml-auto text-xs text-[var(--muted-foreground)] tabular-nums">
                  {`${formatClock(elapsed)} / ${formatClock(total)}`}
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
