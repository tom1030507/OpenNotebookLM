import { describe, expect, it } from 'vitest';
import type { VideoScene, VideoSummary } from '@/lib/api';
import {
  FALLBACK_MODEL,
  MIN_SCENE_SECONDS,
  elapsedSeconds,
  formatClock,
  sceneSeconds,
  sceneTimeline,
  totalSeconds,
  videoSummaryToMarkdown,
} from './videoSummaryTiming';

const scene = (overrides: Partial<VideoScene> = {}): VideoScene => ({
  id: 'scene',
  kind: 'source',
  headline: 'A headline',
  bullets: [],
  narration: 'One two three four five six.',
  document_id: null,
  source_label: null,
  ...overrides,
});

const summary = (overrides: Partial<VideoSummary> = {}): VideoSummary => ({
  project_id: 'project-1',
  project_name: 'Research notes',
  generated_at: '2026-08-20T00:00:00Z',
  model_used: 'test-model',
  scene_count: 2,
  estimated_seconds: 12,
  scenes: [
    scene({
      id: 'title',
      kind: 'title',
      headline: 'Research notes',
      bullets: ['1 source', 'Generated 20 August 2026'],
      narration: 'This is a video summary of Research notes.',
    }),
    scene({
      id: 'doc-1',
      headline: 'Rainfall is rising',
      bullets: ['Rainfall', 'Glaciers'],
      narration: 'This source is about rainfall.',
      document_id: 'doc-1',
      source_label: 'Only source',
    }),
  ],
  ...overrides,
});

describe('sceneSeconds', () => {
  it('grows with the amount of narration', () => {
    const short = sceneSeconds(scene({ narration: 'Three words here.' }));
    const long = sceneSeconds(scene({ narration: 'word '.repeat(100) }));

    expect(long).toBeGreaterThan(short);
  });

  it('keeps a scene with no narration on screen long enough to read', () => {
    expect(sceneSeconds(scene({ narration: '' }))).toBe(MIN_SCENE_SECONDS);
  });
});

describe('sceneTimeline', () => {
  it('starts the first scene at zero', () => {
    expect(sceneTimeline(summary().scenes)[0].start).toBe(0);
  });

  it('starts each scene where the one before it ended', () => {
    const timeline = sceneTimeline(summary().scenes);

    expect(timeline[1].start).toBeCloseTo(timeline[0].start + timeline[0].seconds);
  });

  it('has one entry per scene', () => {
    expect(sceneTimeline(summary().scenes)).toHaveLength(2);
  });

  it('handles a script with no scenes', () => {
    expect(sceneTimeline([])).toEqual([]);
    expect(totalSeconds([])).toBe(0);
  });
});

describe('totalSeconds', () => {
  it('is the whole timeline', () => {
    const timeline = sceneTimeline(summary().scenes);

    expect(totalSeconds(timeline)).toBeCloseTo(
      timeline[0].seconds + timeline[1].seconds,
    );
  });
});

describe('elapsedSeconds', () => {
  const timeline = sceneTimeline(summary().scenes);

  it('is the scene start plus how far into it playback has got', () => {
    expect(elapsedSeconds(timeline, 1, 0.5)).toBeCloseTo(timeline[1].start + 0.5);
  });

  it('never runs past the end of the current scene', () => {
    // A slow voice overruns the estimate; the bar must not enter the next scene.
    expect(elapsedSeconds(timeline, 0, 999)).toBeCloseTo(timeline[0].seconds);
  });

  it('is zero for a scene index that does not exist', () => {
    expect(elapsedSeconds(timeline, 9, 1)).toBe(0);
  });
});

describe('formatClock', () => {
  it('reads as minutes and seconds', () => {
    expect(formatClock(0)).toBe('0:00');
    expect(formatClock(42)).toBe('0:42');
    expect(formatClock(96)).toBe('1:36');
    expect(formatClock(605)).toBe('10:05');
  });

  it('does not show a negative clock', () => {
    expect(formatClock(-3)).toBe('0:00');
  });
});

describe('videoSummaryToMarkdown', () => {
  it('titles the script after the project', () => {
    expect(videoSummaryToMarkdown(summary())).toContain('# Research notes video summary');
  });

  it('says which model wrote the narration', () => {
    expect(videoSummaryToMarkdown(summary())).toContain('test-model');
  });

  it('says when the narration was extracted instead', () => {
    const markdown = videoSummaryToMarkdown(summary({ model_used: FALLBACK_MODEL }));

    expect(markdown).toContain('document structure');
    expect(markdown).not.toContain(FALLBACK_MODEL);
  });

  it('writes every scene, its bullets and its narration', () => {
    const markdown = videoSummaryToMarkdown(summary());

    expect(markdown).toContain('## 1. Research notes');
    expect(markdown).toContain('## 2. Rainfall is rising');
    expect(markdown).toContain('- Glaciers');
    expect(markdown).toContain('This source is about rainfall.');
  });

  it('cites the source a scene came from', () => {
    expect(videoSummaryToMarkdown(summary())).toContain('Source: Only source');
  });
});
