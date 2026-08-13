// @vitest-environment jsdom

import React, { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ResponsiveLayout from './ResponsiveLayout';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function createDesktopMediaQuery() {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const query = {
    matches: false,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
  };

  return {
    install() {
      vi.stubGlobal('matchMedia', vi.fn(() => query));
    },
    enterDesktop() {
      query.matches = true;
      act(() => {
        listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent));
      });
    },
  };
}

function renderWorkspace() {
  return render(
    <ResponsiveLayout
      sidebar={
        <section aria-label="Sources content">
          <button type="button">Sources action</button>
        </section>
      }
      conversationPanel={
        <section aria-label="Conversations panel content">
          <button type="button">New Conversation</button>
        </section>
      }
      rightPanel={
        <section aria-label="Studio content">
          <button type="button">Studio action</button>
        </section>
      }
    >
      <button type="button">Chat action</button>
    </ResponsiveLayout>,
  );
}

describe('ResponsiveLayout component integration', () => {
  it('renders compact and desktop structures from stable CSS-controlled markup with an in-flow toolbar', () => {
    const { container } = renderWorkspace();
    const toolbar = screen.getByRole('navigation', { name: 'Workspace panels' });

    expect(toolbar.className).not.toContain('absolute');
    expect(toolbar.parentElement?.className).toContain('flex-col');
    expect(screen.getByRole('button', { name: 'Open Sources panel' })).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="sources"]')).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="conversations"]')).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="studio"]')).toBeTruthy();
  });

  it('opens a modal drawer with an in-flow close header, traps focus, restores it on every dismissal, and switches panels exclusively', () => {
    renderWorkspace();
    const sourcesTrigger = screen.getByRole('button', { name: 'Open Sources panel' });
    const studioTrigger = screen.getByRole('button', { name: 'Open Studio panel' });

    fireEvent.click(sourcesTrigger);
    const sourcesDialog = screen.getByRole('dialog', { name: 'Sources panel' });
    const sourcesHeader = sourcesDialog.querySelector('header');
    const sourcesClose = within(sourcesDialog).getByRole('button', { name: 'Close Sources panel' });

    expect(sourcesDialog.getAttribute('aria-modal')).toBe('true');
    expect(sourcesHeader).toBeTruthy();
    expect(sourcesHeader?.className).not.toContain('absolute');
    expect(document.activeElement).toBe(sourcesClose);

    fireEvent.keyDown(sourcesClose, { key: 'Tab', shiftKey: true });
    const sourcesAction = within(sourcesDialog).getByRole('button', { name: 'Sources action' });
    expect(document.activeElement).toBe(sourcesAction);

    fireEvent.keyDown(sourcesAction, { key: 'Tab' });
    expect(document.activeElement).toBe(sourcesClose);

    fireEvent.click(studioTrigger);
    const studioDialog = screen.getByRole('dialog', { name: 'Studio panel' });
    expect(screen.queryByRole('dialog', { name: 'Sources panel' })).toBeNull();
    fireEvent.click(within(studioDialog).getByRole('button', { name: 'Close Studio panel' }));
    expect(document.activeElement).toBe(studioTrigger);

    fireEvent.click(sourcesTrigger);
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Sources panel' }), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(sourcesTrigger);

    fireEvent.click(sourcesTrigger);
    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(sourcesTrigger);
  });

  it('mounts each supporting panel exactly once while its drawer is open', () => {
    let sourcesMounts = 0;

    function SourcesProbe() {
      useEffect(() => {
        sourcesMounts += 1;
      }, []);

      return (
        <section aria-label="Sources content">
          <button type="button">Sources action</button>
        </section>
      );
    }

    render(
      <ResponsiveLayout sidebar={<SourcesProbe />}>
        <button type="button">Chat action</button>
      </ResponsiveLayout>,
    );

    expect(sourcesMounts).toBe(1);

    fireEvent.click(screen.getByRole('button', { name: 'Open Sources panel' }));

    expect(sourcesMounts).toBe(1);
    expect(screen.getAllByRole('button', { name: 'Sources action' })).toHaveLength(1);
  });

  it('clears an open drawer and its close affordance when the viewport reaches the desktop breakpoint', () => {
    const media = createDesktopMediaQuery();
    media.install();
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: 'Open Sources panel' }));
    expect(screen.getByRole('dialog', { name: 'Sources panel' })).toBeTruthy();

    media.enterDesktop();

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close Sources panel' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close panel' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Open Sources panel' })).toBeTruthy();
  });

  it('carries the drawer width in a CSS variable so the desktop breakpoint can still override it', () => {
    renderWorkspace();
    fireEvent.click(screen.getByRole('button', { name: 'Open Sources panel' }));

    const drawer = screen.getByRole('dialog', { name: 'Sources panel' });

    expect(drawer.style.width).toBe('');
    expect(drawer.style.getPropertyValue('--workspace-drawer-width')).toBe('min(20rem, 90vw)');
    expect(drawer.className).toContain('w-[var(--workspace-drawer-width)]');
    expect(drawer.className).toContain('lg:w-auto');
  });

  it('keeps the workspace usable when the environment has no matchMedia support', () => {
    vi.stubGlobal('matchMedia', undefined);
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', { name: 'Open Sources panel' }));

    expect(screen.getByRole('dialog', { name: 'Sources panel' })).toBeTruthy();
  });
});
