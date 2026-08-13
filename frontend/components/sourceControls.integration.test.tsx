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
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import ChatArea from './chat/ChatArea';
import StudioPanel from './layout/StudioPanel';
import SourcesPanel from './layout/SourcesPanel';
import TopNav from './layout/TopNav';
import type { Project } from '@/lib/api';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';


const currentProject: Project = {
  id: 'project-1',
  name: '研究筆記',
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
      <button onClick={() => setIsAddSourcesOpen(false)}>外部關閉來源對話框</button>
      <button onClick={() => setIsAddSourcesOpen(true)}>外部重新開啟來源對話框</button>
      <SourcesPanel
        isAddSourcesOpen={isAddSourcesOpen}
        onAddSourcesOpenChange={setIsAddSourcesOpen}
      />
    </ProjectDialogProvider>
  );
}


function openUrlUploader() {
  fireEvent.click(screen.getByRole('button', { name: '新增來源' }));
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

    fireEvent.click(screen.getByRole('button', { name: '上傳來源' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '關閉新增來源' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '關閉新增來源' }));
    fireEvent.click(screen.getByRole('button', { name: '新增來源' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();
  });

  it('focuses the close button, closes with Escape, and restores focus to the opener', () => {
    render(<SourceWorkspace />);
    const opener = screen.getByRole('button', { name: '上傳來源' });

    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '關閉新增來源' }));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '新增來源' })).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('closes the dialog after a URL upload succeeds', async () => {
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '新增來源' })).toBeNull();
    });
  });

  it('keeps the dialog open and surfaces an error after a URL upload fails', async () => {
    useStore.setState({
      createDocument: async () => {
        throw new Error('上傳失敗');
      },
    });
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('Upload failed. Please check the URL and try again.')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();
  });

  it('keeps a busy modal non-dismissible until its upload settles', async () => {
    const upload = deferred<void>();
    useStore.setState({ createDocument: async () => upload.promise });
    render(<SourceWorkspace />);
    openUrlUploader();
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    const dialog = screen.getByRole('dialog', { name: '新增來源' });
    expect(dialog.getAttribute('aria-busy')).toBe('true');
    expect((screen.getByRole('button', { name: '關閉新增來源' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(dialog);
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();

    await act(async () => {
      upload.resolve();
      await upload.promise;
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '新增來源' })).toBeNull();
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

    fireEvent.click(screen.getByRole('button', { name: '外部關閉來源對話框' }));
    fireEvent.click(screen.getByRole('button', { name: '外部重新開啟來源對話框' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();

    await act(async () => {
      firstUpload.resolve();
      await firstUpload.promise;
    });
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();
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
      expect(screen.queryByRole('dialog', { name: '新增來源' })).toBeNull();
    });
  });
});


describe('unavailable workspace controls', () => {
  it('exposes a working theme toggle and user-menu availability states', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    // The 即將推出 placeholder this PR introduced is superseded by the real
    // theme toggle from #3, so the control must now be genuinely usable.
    const themeToggle = screen.getByRole('button', { name: '切換主題' });
    expect((themeToggle as HTMLButtonElement).disabled).toBe(false);

    const userMenuTrigger = screen.getByRole('button', { name: '使用者選單' });
    expect(userMenuTrigger.getAttribute('aria-haspopup')).toBe('menu');
    expect(userMenuTrigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(userMenuTrigger);
    expect(userMenuTrigger.getAttribute('aria-expanded')).toBe('true');
    expect((screen.getByRole('button', { name: '個人資料即將推出' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '登出即將推出' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('states that Studio output features are coming soon', () => {
    render(<StudioPanel />);

    expect(screen.getByText('工作室功能即將推出')).not.toBeNull();
    expect(screen.getByText('音訊、影片、心智圖與報告功能仍在準備中。')).not.toBeNull();
  });
});
