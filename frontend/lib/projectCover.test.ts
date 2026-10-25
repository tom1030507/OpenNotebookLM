import { describe, expect, it } from 'vitest';
import { PROJECT_COVER_COLORS } from './projectCover';

const luminance = (hex: string) => {
  const channels = hex.match(/[\da-f]{2}/gi)!.map((channel) => parseInt(channel, 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
};

const contrast = (foreground: string, background: string) => {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
};

describe('project cover palette', () => {
  it('keeps label contrast above WCAG AA in both themes', () => {
    for (const color of PROJECT_COVER_COLORS) {
      expect(contrast(color.lightForeground, color.lightBackground), color.id).toBeGreaterThanOrEqual(4.5);
      expect(contrast(color.darkForeground, color.darkBackground), color.id).toBeGreaterThanOrEqual(4.5);
    }
  });
});
