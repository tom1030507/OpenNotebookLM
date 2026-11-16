// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Home from '@/app/page';
import OfflineDemoNotice from './OfflineDemoNotice';
import { clearSession, isOfflineDemoSession, OFFLINE_DEMO_TOKEN, storeSession } from '@/lib/session';
import useStore from '@/store/useStore';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

beforeEach(() => {
  window.localStorage.clear();
  clearSession();
  useStore.getState().resetForTests();
  replace.mockReset();
  HTMLElement.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
  clearSession();
  useStore.getState().resetForTests();
  vi.unstubAllGlobals();
});

describe('offline demo workspace', () => {
  it('opens the real workspace with bundled sources and notes while the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Backend unavailable')));
    storeSession(OFFLINE_DEMO_TOKEN, { username: 'demo', email: 'demo@example.com' });
    render(<Home />);

    expect(await screen.findByRole('heading', { name: 'Research demo' })).toBeTruthy();
    expect(await screen.findByRole('heading', { name: 'A guide to checking your sources' })).toBeTruthy();
    expect(await screen.findByText('A reading checklist')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Offline demo' }).textContent).toMatch(/running backend/);
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Exit demo' }));
    expect(isOfflineDemoSession()).toBe(false);
    expect(useStore.getState().currentProject).toBeNull();
    expect(replace).toHaveBeenCalledWith('/login');
  });

  it('does not label a backend-authenticated demo account as offline', () => {
    storeSession('real-backend-token', { username: 'demo', email: 'demo@example.com' });
    render(<OfflineDemoNotice />);
    expect(screen.queryByRole('status', { name: 'Offline demo' })).toBeNull();
  });
});
