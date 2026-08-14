// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Settings from './Settings';
import TopNav from './layout/TopNav';
import ProjectDialogProvider from './ProjectDialogProvider';
import api from '@/lib/api';
import useStore from '@/store/useStore';
import { initializeTheme, THEME_STORAGE_KEY } from '@/lib/theme';

// TopNav navigates on sign-out.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));

const STORE_STORAGE_KEY = 'app-storage';
const initialStoreState = useStore.getState();

const setSystemPreference = (prefersDark: boolean) => {
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
};

function SettingsHarness() {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>Open settings</button>
      <Settings isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}

const themeOption = (name: 'Light' | 'Dark' | 'System') => (
  screen.getByRole('button', { name })
);

const notificationToggle = () => screen.getByRole('checkbox', {
  name: /Processing complete/,
}) as HTMLInputElement;

const openTab = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

const saveChanges = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Settings' })).toBeNull());
};

const storedPreferences = () => JSON.parse(
  window.localStorage.getItem(STORE_STORAGE_KEY) || '{}',
) as { state?: { notifyOnProcessingComplete?: boolean } };

beforeEach(() => {
  setSystemPreference(false);
  initializeTheme();
});

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.style.removeProperty('color-scheme');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('settings that are presented as saveable', () => {
  it('applies a dark theme on save and shows it again when reopened', async () => {
    render(<SettingsHarness />);

    fireEvent.click(themeOption('Dark'));
    await saveChanges();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');

    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }));

    expect(themeOption('Dark').getAttribute('aria-pressed')).toBe('true');
    expect(themeOption('System').getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps a saved theme across a reload', async () => {
    render(<SettingsHarness />);

    fireEvent.click(themeOption('Dark'));
    await saveChanges();

    // What the pre-paint script does on the next page load.
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.style.removeProperty('color-scheme');
    initializeTheme();

    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('discards a theme choice that was cancelled', () => {
    render(<SettingsHarness />);

    fireEvent.click(themeOption('Dark'));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }));

    expect(themeOption('System').getAttribute('aria-pressed')).toBe('true');
  });

  it('hands the theme back to the operating system when System is saved', async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    setSystemPreference(true);
    render(<SettingsHarness />);

    expect(themeOption('Light').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(themeOption('System'));
    await saveChanges();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('agrees with the toolbar theme toggle in both directions', async () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'Toggle theme' }));
    expect(document.documentElement.dataset.theme).toBe('dark');

    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    expect(themeOption('Dark').getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(themeOption('Light'));
    await saveChanges();

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('persists the processing-complete notification preference across a remount', async () => {
    const view = render(<SettingsHarness />);

    openTab('Notifications');
    expect(notificationToggle().checked).toBe(true);

    fireEvent.click(notificationToggle());
    await saveChanges();

    expect(useStore.getState().notifyOnProcessingComplete).toBe(false);
    expect(storedPreferences().state?.notifyOnProcessingComplete).toBe(false);

    view.unmount();
    render(<SettingsHarness />);
    openTab('Notifications');

    expect(notificationToggle().checked).toBe(false);
  });

  it('restores a stored notification preference on reload', async () => {
    window.localStorage.setItem(STORE_STORAGE_KEY, JSON.stringify({
      state: { sidebarOpen: true, studioOpen: true, notifyOnProcessingComplete: false },
      version: 0,
    }));

    await useStore.persist.rehydrate();

    expect(useStore.getState().notifyOnProcessingComplete).toBe(false);
  });

  it('discards a notification change that was cancelled', () => {
    render(<SettingsHarness />);

    openTab('Notifications');
    fireEvent.click(notificationToggle());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(useStore.getState().notifyOnProcessingComplete).toBe(true);
  });
});

describe('settings that cannot be honoured yet', () => {
  it('disables the language, model, key and endpoint controls', () => {
    render(<Settings isOpen onClose={() => {}} />);

    expect((screen.getByRole('combobox', { name: 'Language' }) as HTMLSelectElement).disabled)
      .toBe(true);

    openTab('API Keys');

    expect((screen.getByRole('combobox', { name: 'Model' }) as HTMLSelectElement).disabled)
      .toBe(true);
    expect((screen.getByLabelText('API Key') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('Endpoint URL') as HTMLInputElement).disabled).toBe(true);
  });

  it('does not offer auto-save as a choice the app cannot make', () => {
    render(<Settings isOpen onClose={() => {}} />);

    const autoSave = screen.getByRole('checkbox', {
      name: /Auto-save conversations/,
    }) as HTMLInputElement;

    expect(autoSave.disabled).toBe(true);
    expect(autoSave.checked).toBe(true);
  });

  it('reports no storage figures it cannot measure', () => {
    render(<Settings isOpen onClose={() => {}} />);

    openTab('Data & Storage');

    ['124 MB', '56 MB', '12 MB', '192 MB'].forEach((figure) => {
      expect(screen.queryByText(figure)).toBeNull();
    });
    expect((screen.getByRole('button', { name: /Export Data/ }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it('clears the real server cache', async () => {
    const clearCache = vi.spyOn(api, 'clearCache').mockResolvedValue(3);
    render(<Settings isOpen onClose={() => {}} />);

    openTab('Data & Storage');
    fireEvent.click(screen.getByRole('button', { name: 'Clear Cache' }));

    await waitFor(() => expect(clearCache).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/3 cached/)).toBeTruthy();
  });

  it('reports a failed cache clear instead of pretending it worked', async () => {
    vi.spyOn(api, 'clearCache').mockRejectedValue(new Error('offline'));
    render(<Settings isOpen onClose={() => {}} />);

    openTab('Data & Storage');
    fireEvent.click(screen.getByRole('button', { name: 'Clear Cache' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
  });
});
