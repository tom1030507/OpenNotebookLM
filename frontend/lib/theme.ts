export type Theme = 'light' | 'dark';

/**
 * What the reader asked for, which is not always a theme: `system` means "keep
 * following the operating system", and is stored as the absence of a choice.
 */
export type ThemePreference = Theme | 'system';

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

export function systemPrefersDark(): boolean {
  try {
    return typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    // Light remains the safe default when the system preference is unavailable.
    return false;
  }
}

/** The choice in force, for controls that have to show it back to the reader. */
export function readThemePreference(): ThemePreference {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === 'light' || storedTheme === 'dark') {
      return storedTheme;
    }
  } catch {
    // Nothing recorded is indistinguishable from nothing readable.
  }

  return 'system';
}

export function resolveThemePreference(preference: ThemePreference): Theme {
  if (preference === 'light' || preference === 'dark') {
    return preference;
  }

  return systemPrefersDark() ? 'dark' : 'light';
}

/**
 * Record a choice and apply it right away.
 *
 * Every control that changes the theme goes through here, so the toolbar toggle
 * and the Settings dialog can never end up disagreeing about what is in force.
 */
export function applyThemePreference(
  preference: ThemePreference,
  root: HTMLElement = document.documentElement,
): Theme {
  const theme = resolveThemePreference(preference);

  applyTheme(theme, root);

  try {
    if (preference === 'system') {
      // Storing nothing is what makes the next load follow the system again.
      window.localStorage.removeItem(THEME_STORAGE_KEY);
    } else {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    }
  } catch {
    // The current-session choice still applies if persistence is unavailable.
  }

  return theme;
}

/**
 * Apply the stored choice before the first paint.
 *
 * The root layout ships this function's source as an inline script, so it has
 * to stay self-contained: it cannot call the helpers above, and the storage key
 * has to be written out literally.
 */
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
