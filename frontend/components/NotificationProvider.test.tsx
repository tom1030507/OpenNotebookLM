// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import toast from 'react-hot-toast';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import NotificationProvider from './NotificationProvider';

beforeEach(() => {
  // react-hot-toast asks for prefers-reduced-motion, which jsdom lacks.
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

afterEach(() => {
  act(() => toast.remove());
  cleanup();
  vi.unstubAllGlobals();
});

describe('NotificationProvider', () => {
  it('draws toasts on a themed surface below the top bar (#228)', async () => {
    render(<NotificationProvider />);

    act(() => {
      toast.success('Paper is ready');
    });

    const message = await screen.findByText('Paper is ready');
    const bar = message.closest('[role="status"]')?.parentElement as HTMLElement;
    expect(bar.style.background).toBe('var(--popover)');
    expect(bar.style.color).toBe('var(--card-foreground)');

    const container = bar.closest('[style*="position: fixed"]') as HTMLElement;
    expect(container.style.top).toBe('64px');
  });
});
