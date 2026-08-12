// @vitest-environment jsdom

import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import ChatArea from './chat/ChatArea';
import SourcesPanel from './layout/SourcesPanel';
import type { Project } from '@/lib/api';
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


function SourceWorkspace() {
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);

  return (
    <>
      <ChatArea onAddSourcesOpenChange={setIsAddSourcesOpen} />
      <SourcesPanel
        isAddSourcesOpen={isAddSourcesOpen}
        onAddSourcesOpenChange={setIsAddSourcesOpen}
      />
    </>
  );
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
  it('opens the Add Sources dialog when a selected project user clicks either ChatArea entry point', () => {
    render(<SourceWorkspace />);

    fireEvent.click(screen.getByRole('button', { name: '上傳來源' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '關閉新增來源' }));
    expect(screen.queryByRole('dialog', { name: '新增來源' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '新增來源' }));
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();
  });

  it('closes the dialog after a URL upload succeeds', async () => {
    render(<SourceWorkspace />);

    fireEvent.click(screen.getByRole('button', { name: '新增來源' }));
    fireEvent.click(screen.getByRole('button', { name: 'URL' }));
    fireEvent.change(screen.getByPlaceholderText('Enter website URL...'), {
      target: { value: 'https://example.com' },
    });
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

    fireEvent.click(screen.getByRole('button', { name: '新增來源' }));
    fireEvent.click(screen.getByRole('button', { name: 'URL' }));
    fireEvent.change(screen.getByPlaceholderText('Enter website URL...'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('Upload failed. Please check the URL and try again.')).not.toBeNull();
    expect(screen.getByRole('dialog', { name: '新增來源' })).not.toBeNull();
  });
});
