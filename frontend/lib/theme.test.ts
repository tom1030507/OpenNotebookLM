// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import RootLayout from '@/app/layout';
import TopNav from '@/components/layout/TopNav';
import ProjectDialogProvider from '@/components/ProjectDialogProvider';
import {
  applyTheme,
  initializeTheme,
  resolveInitialTheme,
  THEME_STORAGE_KEY,
} from './theme';

vi.mock('@/app/globals.css', () => ({}));

function setSystemPreference(prefersDark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query === '(prefers-color-scheme: dark)' && prefersDark,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.style.removeProperty('color-scheme');
  vi.unstubAllGlobals();
});

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
    applyTheme('dark', document.documentElement);

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });
});

describe('initializeTheme', () => {
  it('applies a stored theme to the real document root before React renders', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    setSystemPreference(false);

    initializeTheme();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('falls back to light when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined);

    initializeTheme();

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
  });

  it('uses a stored preference even when matchMedia throws', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    vi.stubGlobal('matchMedia', () => {
      throw new Error('unavailable');
    });

    initializeTheme();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('runs the layout pre-paint script against the real document root', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    setSystemPreference(false);

    const markup = renderToStaticMarkup(React.createElement(RootLayout, null, null));
    const script = new DOMParser()
      .parseFromString(markup, 'text/html')
      .querySelector('script');

    expect(script).not.toBeNull();
    new Function(script?.textContent ?? '')();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it('lets the layout pre-paint script fall back to light when matchMedia throws', () => {
    vi.stubGlobal('matchMedia', () => {
      throw new Error('unavailable');
    });

    const markup = renderToStaticMarkup(React.createElement(RootLayout, null, null));
    const script = new DOMParser()
      .parseFromString(markup, 'text/html')
      .querySelector('script');

    expect(script).not.toBeNull();
    new Function(script?.textContent ?? '')();

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
  });
});

describe('TopNav theme toggle', () => {
  it('keeps a pre-painted dark icon in sync and persists the next selected theme', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    setSystemPreference(false);
    initializeTheme();

    // TopNav consumes the project-dialog context once PR #6 is in.
    render(React.createElement(ProjectDialogProvider, null, React.createElement(TopNav)));

    const toggle = screen.getByRole('button', { name: 'Toggle theme' });
    expect(screen.getByRole('button', { name: 'Toggle theme' })).toBe(toggle);
    expect(toggle.querySelector('[data-theme-icon="sun"]')).not.toBeNull();
    expect(toggle.querySelector('[data-theme-icon="moon"]')).not.toBeNull();

    fireEvent.click(toggle);

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');

    document.documentElement.removeAttribute('data-theme');
    document.documentElement.style.removeProperty('color-scheme');
    initializeTheme();

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
  });
});
