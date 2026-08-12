export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'open-notebook-theme';

export function resolveInitialTheme(
  storedTheme: string | null | undefined,
  systemPrefersDark: boolean,
): Theme {
  if (storedTheme === 'light' || storedTheme === 'dark') {
    return storedTheme;
  }

  return systemPrefersDark ? 'dark' : 'light';
}

export function applyTheme(theme: Theme, root: HTMLElement): void {
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

export function initializeTheme(): Theme {
  const root = document.documentElement;
  let storedTheme: string | null = null;

  try {
    storedTheme = window.localStorage.getItem('open-notebook-theme');
  } catch {
    // Theme selection still follows the system preference when storage is unavailable.
  }

  let theme: Theme = 'light';

  if (storedTheme === 'light' || storedTheme === 'dark') {
    theme = storedTheme;
  } else {
    try {
      if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        theme = 'dark';
      }
    } catch {
      // Light remains the safe default when system preference is unavailable.
    }
  }

  root.dataset.theme = theme;
  root.style.colorScheme = theme;

  return theme;
}
