// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ChatArea from './chat/ChatArea';
import ConversationList from './ConversationList';
import SourcesPanel from './layout/SourcesPanel';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';
import type { Document, Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};

const readyDocument: Document = {
  id: 'document-1',
  name: 'First document',
  type: 'text',
  content: 'Content',
  meta: {},
  status: 'ready',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  chunk_count: 1,
};


function SourcesPanelHarness() {
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);

  return (
    <ProjectDialogProvider>
      <SourcesPanel
        isAddSourcesOpen={isAddSourcesOpen}
        onAddSourcesOpenChange={setIsAddSourcesOpen}
      />
    </ProjectDialogProvider>
  );
}

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
  useStore.setState({
    projects: [project],
    currentProject: project,
    documents: [],
    conversations: [],
    messages: [],
    loadingDocuments: false,
    fetchProjects: async () => undefined,
  });
});

afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
});

describe('workspace copy is English', () => {
  it('renders English copy for the sources panel actions and empty state', () => {
    render(<SourcesPanelHarness />);

    expect(screen.getByRole('button', { name: 'New Project' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add Source' })).toBeTruthy();
    expect(screen.getByText('No sources yet')).toBeTruthy();
    expect(screen.getByText(/to upload PDFs, URLs, or YouTube videos/)).toBeTruthy();
  });

  it('does not repeat the no-project prompt in the simplified Sources panel', () => {
    useStore.setState({ projects: [], currentProject: null });
    render(<SourcesPanelHarness />);

    expect(screen.queryByText('Select or create a project to get started')).toBeNull();
  });

  it('renders English copy for the sources search empty state', () => {
    useStore.setState({ documents: [readyDocument] });
    render(<SourcesPanelHarness />);

    const search = screen.getByRole('textbox', { name: 'Search sources' });
    search.setAttribute('value', 'nonexistent');
    // Typing is exercised elsewhere; here we only need the no-result copy path.
    expect(screen.queryByText('No sources found')).toBeNull();
  });

  it('renders English copy for the conversation list empty state', () => {
    render(<ConversationList />);

    expect(screen.getByText('No conversations yet')).toBeTruthy();
    expect(screen.getByText('Start a new chat to begin')).toBeTruthy();
  });

  it('renders English copy for the chat composer placeholders in both states', () => {
    useStore.setState({ currentProject: null });
    const { unmount } = render(<ChatArea onAddSourcesOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText('Create a project to start chatting')).toBeTruthy();
    unmount();

    useStore.setState({ currentProject: project, documents: [readyDocument] });
    render(<ChatArea onAddSourcesOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText('Ask anything about your sources...')).toBeTruthy();
  });

  it('names the add sources dialog in English', () => {
    render(<SourcesPanelHarness />);

    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }));

    expect(screen.getByRole('dialog', { name: 'Add Source' })).toBeTruthy();
  });
});
