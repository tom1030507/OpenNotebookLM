import type { VideoScene, VideoSummary } from '@/lib/api';

/** Reported by the API when the documents' own structure wrote the script. */
export const FALLBACK_MODEL = 'fallback';

/**
 * Reading pace, matching the backend's `WORDS_PER_SECOND`. Only the progress
 * bar depends on it: playback advances when the voice finishes a scene, so an
 * estimate a few seconds out costs nothing. It does set the pace of the silent
 * slideshow shown where speech is unavailable.
 */
export const WORDS_PER_SECOND = 2.6;

/** A scene with no narration still has to stay on screen long enough to read. */
export const MIN_SCENE_SECONDS = 1;

/** Where one scene sits on the timeline, in seconds. */
export interface SceneTiming {
  start: number;
  seconds: number;
}

/**
 * How long a scene is expected to take to read out.
 *
 * @param scene The scene.
 * @returns Seconds, with a floor so a silent scene is still readable.
 */
export function sceneSeconds(scene: VideoScene): number {
  const words = scene.narration.trim().split(/\s+/).filter(Boolean).length;

  return Math.max(MIN_SCENE_SECONDS, words / WORDS_PER_SECOND);
}

/**
 * Lay the scenes out on a timeline.
 *
 * @param scenes The script's scenes, in playback order.
 * @returns Each scene's start and duration, in the same order.
 */
export function sceneTimeline(scenes: VideoScene[]): SceneTiming[] {
  let start = 0;

  return scenes.map((scene) => {
    const seconds = sceneSeconds(scene);
    const timing = { start, seconds };
    start += seconds;

    return timing;
  });
}

/**
 * How long the whole script is expected to take.
 *
 * @param timeline The laid-out scenes.
 * @returns Seconds, 0 for an empty script.
 */
export function totalSeconds(timeline: SceneTiming[]): number {
  const last = timeline[timeline.length - 1];

  return last ? last.start + last.seconds : 0;
}

/**
 * Where the progress bar should sit.
 *
 * Clamped to the current scene's own length. A voice slower than the estimate
 * would otherwise walk the bar into the following scenes while the same slide
 * was still on screen, which reads as the player having lost its place.
 *
 * @param timeline The laid-out scenes.
 * @param index Scene being played.
 * @param withinScene Seconds since that scene started.
 * @returns Seconds from the start of the script, or 0 for an unknown scene.
 */
export function elapsedSeconds(
  timeline: SceneTiming[],
  index: number,
  withinScene: number,
): number {
  const timing = timeline[index];
  if (!timing) return 0;

  return timing.start + Math.min(Math.max(0, withinScene), timing.seconds);
}

/**
 * Format a duration the way a player does.
 *
 * @param seconds Seconds; negatives are treated as zero.
 * @returns `m:ss`.
 */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);

  return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * Serialise the script as Markdown, for the download the dialog offers.
 *
 * The narration is the substance of a video summary, so the download is the
 * script rather than a list of headlines: it is the only way to keep what was
 * said once the playback ends.
 *
 * @param summary The script.
 * @returns Markdown, ending in a newline.
 */
export function videoSummaryToMarkdown(summary: VideoSummary): string {
  const lines = [`# ${summary.project_name} video summary`, ''];

  // Not "no model was used": the API reports the fallback both when no provider
  // is configured and when one answered with something unusable, and claiming
  // the second case never called a model would be false.
  lines.push(
    summary.model_used === FALLBACK_MODEL
      ? '_Narration taken from document structure rather than from a language model._'
      : `_Narration written by ${summary.model_used}._`,
    '',
  );

  summary.scenes.forEach((scene, index) => {
    lines.push(`## ${index + 1}. ${scene.headline}`, '');

    if (scene.source_label) {
      lines.push(`Source: ${scene.source_label}`, '');
    }

    if (scene.bullets.length) {
      lines.push(...scene.bullets.map((bullet) => `- ${bullet}`), '');
    }

    lines.push(scene.narration, '');
  });

  return lines.join('\n');
}
