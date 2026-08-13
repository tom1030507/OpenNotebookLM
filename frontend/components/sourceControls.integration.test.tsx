// @vitest-environment jsdom

import { useState } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ChatArea from './chat/ChatArea';
import StudioPanel from './layout/StudioPanel';
import SourcesPanel from './layout/SourcesPanel';
import TopNav from './layout/TopNav';
import type { Project } from '@/lib/api';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';

// TopNav navigates on sign-out.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));



const currentProject: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};


function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
}


function SourceWorkspace() {
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);

  return (
    <ProjectDialogProvider>
      <ChatArea onAddSourcesOpenChange={setIsAddSourcesOpen} />
      <SourcesPanel
        isAddSourcesOpen={isAddSourcesOpen}
        onAddSourcesOpenChange={setIsAddSourcesOpen}
      />
    </ProjectDialogProvider>
  );
}


function ReopenableSourcesPanel() {
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(true);

  return (
    <ProjectDialogProvider>
      <button onClick={() => setIsAddSourcesOpen(false)}>Externally close the sources dialog</button>
      <button onClick={() => setIsAddSourcesOpen(true)}>Externally reopen the sources dialog</button>
      <SourcesPanel
        isAddSourcesOpen={isAddSourcesOpen}
        onAddSourcesOpenChange={setIsAddSourcesOpen}
      />
    </ProjectDialogProvider>
  );
}


function openUrlUploader() {
  fireEvent.click(screen.getByRole('button', { name: 'Attach file' }));
  fireEvent.click(screen.getByRole('button', { name: 'URL' }));
  const urlInput = screen.getByPlaceholderText('Enter website URL...');
  fireEvent.change(urlInput, { target: { value: 'https://example.com' } });

  return urlInput;
}


beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
  useStore.setState({
    projects: [currentProject],
    currentProject,
    documents: [],
    messages: [],
    loadingDocuments: false,
    fetchProjects: async () => undefined,
    createDocument: async () => undefined,
    uploadDocument: async () => undefined,
  });
});

afterEach(() => {
  cleanup();
  useStore.setState(useStore.getInitialState(), true);
});


describe('Add Sources controls', () => {
  it('opens the dialog from the welcome CTA, paperclip, and SourcesPanel Add Source button', () => {
    render(<SourceWorkspace />);

    fireEvent.click(screen.getByRole('button', { name: 'Upload sources' }));
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Close add sources dialog' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }));
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Close add sources dialog' }));
    fireEvent.click(screen.getByRole('button', { name: 'Attach file' }));
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();
  });

  it('focuses the close button, closes with Escape, and restores focus to the opener', () => {
    render(<SourceWorkspace />);
    const opener = screen.getByRole('button', { name: 'Upload sources' });

    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close add sources dialog' }));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Add Source' })).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('closes the dialog after a URL upload succeeds', async () => {
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Add Source' })).toBeNull();
    });
  });

  it('keeps the dialog open and surfaces an error after a URL upload fails', async () => {
    useStore.setState({
      createDocument: async () => {
        throw new Error('Upload failed');
      },
    });
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('Upload failed. Please check the URL and try again.')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();
  });

  it('keeps a busy modal non-dismissible until its upload settles', async () => {
    const upload = deferred<void>();
    useStore.setState({ createDocument: async () => upload.promise });
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    const dialog = screen.getByRole('dialog', { name: 'Add Source' });
    expect(dialog.getAttribute('aria-busy')).toBe('true');
    expect((screen.getByRole('button', { name: 'Close add sources dialog' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(dialog);
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();

    await act(async () => {
      upload.resolve();
      await upload.promise;
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Add Source' })).toBeNull();
    });
  });

  it('does not let a stale upload completion close a newly opened dialog', async () => {
    const firstUpload = deferred<void>();
    useStore.setState({ createDocument: async () => firstUpload.promise });
    render(<ReopenableSourcesPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'URL' }));
    fireEvent.change(screen.getByPlaceholderText('Enter website URL...'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    fireEvent.click(screen.getByRole('button', { name: 'Externally close the sources dialog' }));
    fireEvent.click(screen.getByRole('button', { name: 'Externally reopen the sources dialog' }));
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();

    await act(async () => {
      firstUpload.resolve();
      await firstUpload.promise;
    });
    expect(screen.getByRole('dialog', { name: 'Add Source' })).not.toBeNull();
  });

  it('submits one URL upload after rapid Enter and Add interactions while the button becomes busy', async () => {
    const upload = deferred<void>();
    let uploadRequests = 0;
    useStore.setState({
      createDocument: async () => {
        uploadRequests += 1;
        return upload.promise;
      },
    });
    render(<SourceWorkspace />);
    const urlInput = openUrlUploader();
    const addButton = screen.getByRole('button', { name: 'Add' });

    await act(async () => {
      fireEvent.keyDown(urlInput, { key: 'Enter' });
      fireEvent.click(addButton);
      fireEvent.keyDown(urlInput, { key: 'Enter' });
    });

    expect(uploadRequests).toBe(1);
    expect((addButton as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      upload.resolve();
      await upload.promise;
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Add Source' })).toBeNull();
    });
  });
});


describe('unavailable workspace controls', () => {
  it('exposes a working theme toggle and user-menu availability states', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    // The coming soon placeholder this PR introduced is superseded by the real
    // theme toggle from #3, so the control must now be genuinely usable.
    const themeToggle = screen.getByRole('button', { name: 'Toggle theme' });
    expect((themeToggle as HTMLButtonElement).disabled).toBe(false);

    const userMenuTrigger = screen.getByRole('button', { name: 'User menu' });
    expect(userMenuTrigger.getAttribute('aria-haspopup')).toBe('menu');
    expect(userMenuTrigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(userMenuTrigger);
    expect(userMenuTrigger.getAttribute('aria-expanded')).toBe('true');
    // Profile and Sign out are implemented now, so they must be usable.
    expect((screen.getByRole('button', { name: 'Profile' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Sign out' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('states that Studio output features are coming soon', () => {
    render(<StudioPanel />);

    expect(screen.getByText('Studio is coming soon')).not.toBeNull();
    expect(screen.getByText('Audio, video, mind maps and reports are still in preparation.')).not.toBeNull();
  });
});
