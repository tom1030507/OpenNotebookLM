import { describe, expect, it } from 'vitest';
import { applyTheme, resolveInitialTheme } from './theme';

describe('resolveInitialTheme', () => {
  it('uses a stored light preference when the system prefers dark', () => {
    expect(resolveInitialTheme('light', true)).toBe('light');
  });

  it('uses the system preference when no theme is stored', () => {
    expect(resolveInitialTheme(null, true)).toBe('dark');
    expect(resolveInitialTheme(null, false)).toBe('light');
  });

  it('ignores an invalid stored preference and uses the system preference', () => {
    expect(resolveInitialTheme('system', false)).toBe('light');
  });
});

describe('applyTheme', () => {
  it('sets the active theme and browser color scheme on the document root', () => {
    const root = {
      dataset: {},
      style: {},
    } as HTMLElement;

    applyTheme('dark', root);

    expect(root.dataset.theme).toBe('dark');
    expect(root.style.colorScheme).toBe('dark');
  });
});
