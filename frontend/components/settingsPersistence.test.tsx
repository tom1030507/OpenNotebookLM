// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Settings from './Settings';
import TopNav from './layout/TopNav';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';
import { initializeTheme, THEME_STORAGE_KEY } from '@/lib/theme';
import api from '@/lib/api';

// TopNav navigates on sign-out.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));

const STORE_STORAGE_KEY = 'app-storage';

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
  useStore.getState().resetForTests();
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

describe('settings with unavailable provider controls', () => {
  it('offers personal API key management in the API Keys tab', () => {
    render(<Settings isOpen onClose={() => {}} />);

    openTab('API Keys');

    expect(screen.getByRole('heading', { name: 'Personal API keys' })).toBeTruthy();
  });

  it('creates a key once, lists metadata, and revokes it', async () => {
    vi.spyOn(api, 'listPersonalApiKeys').mockResolvedValue([]);
    vi.spyOn(api, 'createPersonalApiKey').mockResolvedValue({
      id: 'key-1',
      name: 'nightly job',
      api_key: 'onlm_once-only',
      created_at: '2026-10-26T00:00:00+00:00',
      last_used_at: null,
    });
    vi.spyOn(api, 'revokePersonalApiKey').mockResolvedValue();
    render(<Settings isOpen onClose={() => {}} />);

    openTab('API Keys');
    fireEvent.change(await screen.findByLabelText('API key name'), {
      target: { value: 'nightly job' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }));

    expect(await screen.findByLabelText('New personal API key')).toHaveProperty(
      'value',
      'onlm_once-only',
    );
    expect(screen.getByText('nightly job')).toBeTruthy();
    expect(api.createPersonalApiKey).toHaveBeenCalledWith('nightly job');

    fireEvent.click(screen.getByRole('button', { name: 'Revoke API key nightly job' }));

    await waitFor(() => expect(api.revokePersonalApiKey).toHaveBeenCalledWith('key-1'));
    expect(screen.queryByLabelText('New personal API key')).toBeNull();
    await waitFor(() => expect(screen.queryByText('nightly job')).toBeNull());
  });

  it('hides the one-time secret when Settings closes', async () => {
    vi.spyOn(api, 'listPersonalApiKeys').mockResolvedValue([]);
    vi.spyOn(api, 'createPersonalApiKey').mockResolvedValue({
      id: 'key-2',
      name: 'backup job',
      api_key: 'onlm_hidden-after-close',
      created_at: '2026-10-26T00:00:00+00:00',
      last_used_at: null,
    });
    render(<SettingsHarness />);
    openTab('API Keys');
    fireEvent.change(await screen.findByLabelText('API key name'), {
      target: { value: 'backup job' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }));
    expect(await screen.findByLabelText('New personal API key')).toHaveProperty(
      'value',
      'onlm_hidden-after-close',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }));
    await screen.findByRole('heading', { name: 'Personal API keys' });

    expect(screen.queryByLabelText('New personal API key')).toBeNull();
  });

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

  it('does not offer process-wide cache clearing', () => {
    render(<Settings isOpen onClose={() => {}} />);

    openTab('Data & Storage');

    expect(screen.queryByRole('button', { name: 'Clear Cache' })).toBeNull();
    expect(screen.queryByText(/Clear Cache drops/)).toBeNull();
  });
});
