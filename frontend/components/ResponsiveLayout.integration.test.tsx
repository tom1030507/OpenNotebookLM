// @vitest-environment jsdom

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResponsiveLayout from './ResponsiveLayout';
import ChatArea from './chat/ChatArea';
import useStore from '@/store/useStore';
import useDialogFocus from '@/hooks/useDialogFocus';

afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
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

function PortalDialogPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const initialFocusRef = useRef<HTMLButtonElement>(null);
  useDialogFocus({ isOpen, onClose: () => setIsOpen(false), dialogRef, initialFocusRef });

  return <>
    <button onClick={() => setIsOpen(true)}>Open mind map</button>
    {isOpen && createPortal(
      <div role="dialog" aria-label="Mind map" ref={dialogRef}>
        <button ref={initialFocusRef}>Full screen</button>
        <button>Download mind map</button>
      </div>,
      document.body,
    )}
  </>;
}

describe('ResponsiveLayout component integration', () => {
  it('leaves Tab navigation and focus wrapping to a dialog portaled outside the drawer', async () => {
    const user = userEvent.setup();
    render(<ResponsiveLayout rightPanel={<PortalDialogPanel />}><button>Chat</button></ResponsiveLayout>);
    await user.click(screen.getByRole('button', { name: 'Open Studio panel' }));
    await user.click(screen.getByRole('button', { name: 'Open mind map' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Full screen' }));

    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Download mind map' }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Full screen' }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Download mind map' }));
  });

  it('closes only the portaled dialog when it handles Escape and keeps the drawer open', async () => {
    const user = userEvent.setup();
    render(<ResponsiveLayout rightPanel={<PortalDialogPanel />}><button>Chat</button></ResponsiveLayout>);
    await user.click(screen.getByRole('button', { name: 'Open Studio panel' }));
    const mapTrigger = screen.getByRole('button', { name: 'Open mind map' });
    await user.click(mapTrigger);

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Mind map' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Studio panel' })).toBeTruthy();
    expect(document.activeElement).toBe(mapTrigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open Studio panel' }));
  });

  it('dismisses the mobile studio drawer and focuses the question drafted into chat', async () => {
    useStore.setState({
      currentProject: {
        id: 'project-1', name: 'Research', description: null, meta_json: {},
        created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:00:00Z',
        document_count: 1, conversation_count: 0,
      },
      documents: [{
        id: 'source-1', name: 'Research source', type: 'text', meta: {}, status: 'ready',
        created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:00:00Z', chunk_count: 1,
      }],
    });
    render(
      <ResponsiveLayout rightPanel={
        <button onClick={() => useStore.getState().draftMindMapQuestion('project-1', 'Explain attention.')}>
          Ask in chat
        </button>
      }>
        <ChatArea onAddSourcesOpenChange={() => undefined} />
      </ResponsiveLayout>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Open Studio panel' }));
    const drawer = screen.getByRole('dialog', { name: 'Studio panel' });

    fireEvent.click(within(drawer).getByRole('button', { name: 'Ask in chat' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    const composer = screen.getByRole('textbox') as HTMLTextAreaElement;
    await waitFor(() => expect(document.activeElement).toBe(composer));
    expect(composer.value).toBe('Explain attention.');
    expect(useStore.getState().pendingMindMapQuestion).toBeNull();
    expect(screen.getByRole('button', { name: 'Open Studio panel' })).toBeTruthy();
  });

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
