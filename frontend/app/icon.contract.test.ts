// @vitest-environment jsdom

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';


const iconPath = join(__dirname, 'icon.svg');
const icon = readFileSync(iconPath, 'utf8');

describe('app/icon.svg', () => {
  /**
   * A favicon is fetched as an image, not parsed as part of the document, so a
   * browser that cannot decode it shows nothing at all — no console error, no
   * fallback. XML is stricter than the HTML the rest of the app is written in.
   */
  it('parses as XML, the way a browser decoding it as an image would', () => {
    const parsed = new DOMParser().parseFromString(icon, 'image/svg+xml');

    expect(parsed.querySelector('parsererror')).toBeNull();
    expect(parsed.documentElement.tagName).toEqual('svg');
  });

  it('keeps double hyphens out of its comments, which XML forbids', () => {
    const comments = icon.match(/<!--[\s\S]*?-->/g) ?? [];

    expect(comments.length).toBeGreaterThan(0);
    for (const comment of comments) {
      expect(comment.slice('<!--'.length, -'-->'.length)).not.toContain('--');
    }
  });

  it('scales from a viewBox, so one file serves every favicon size', () => {
    expect(icon).toContain('viewBox="0 0 24 24"');
  });

  /**
   * The favicon cannot reach the theme: it is loaded outside the document, so
   * a `var(--primary)` stop resolves to nothing and the mark renders unpainted.
   */
  it('pins its colours as literal hex rather than theme tokens', () => {
    const parsed = new DOMParser().parseFromString(icon, 'image/svg+xml');
    const stops = Array.from(parsed.querySelectorAll('stop')).map((stop) =>
      stop.getAttribute('stop-color'),
    );

    expect(stops.length).toBeGreaterThan(0);
    for (const stop of stops) {
      expect(stop).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  /**
   * The component's lightest edge is 0.9 units, which is 0.6 device pixels at
   * 16px and renders as a smear. The favicon is a redraw, not a reduction, so
   * every edge here has to clear one pixel at the smallest size it is used.
   */
  it('keeps every edge over a device pixel wide at 16px', () => {
    const parsed = new DOMParser().parseFromString(icon, 'image/svg+xml');
    const widths = Array.from(parsed.querySelectorAll('path')).map((path) =>
      Number(path.getAttribute('stroke-width')),
    );

    expect(widths.length).toBeGreaterThan(0);
    for (const width of widths) {
      // 24 user units render into 16 device pixels.
      expect(width * (16 / 24)).toBeGreaterThan(1);
    }
  });
});
