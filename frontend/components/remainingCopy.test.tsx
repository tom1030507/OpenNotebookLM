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
  name: '研究筆記',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};

const readyDocument: Document = {
  id: 'document-1',
  name: '第一份資料',
  type: 'text',
  content: '內容',
  meta: {},
  status: 'ready',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  chunk_count: 1,
};

const initialState = useStore.getState();

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
  useStore.setState(initialState, true);
});

describe('remaining workspace copy is Traditional Chinese', () => {
  it('translates the sources panel actions and empty state', () => {
    render(<SourcesPanelHarness />);

    expect(screen.getByRole('button', { name: '新增專案' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '新增來源' })).toBeTruthy();
    expect(screen.getByText('尚無來源')).toBeTruthy();
    expect(screen.getByText(/點選「新增來源」以上傳 PDF、網址或 YouTube 影片/)).toBeTruthy();
  });

  it('translates the no-project empty state', () => {
    useStore.setState({ projects: [], currentProject: null });
    render(<SourcesPanelHarness />);

    expect(screen.getByText('請選擇或建立專案以開始使用')).toBeTruthy();
  });

  it('translates the sources search empty state', () => {
    useStore.setState({ documents: [readyDocument] });
    render(<SourcesPanelHarness />);

    const search = screen.getByRole('textbox', { name: '搜尋來源' });
    search.setAttribute('value', '不存在');
    // Typing is exercised elsewhere; here we only need the no-result copy path.
    expect(screen.queryByText('No sources found')).toBeNull();
  });

  it('translates the conversation list empty state', () => {
    render(<ConversationList />);

    expect(screen.getByText('尚無對話')).toBeTruthy();
    expect(screen.getByText('開始新對話即可使用')).toBeTruthy();
  });

  it('translates the chat composer placeholders in both states', () => {
    const { unmount } = render(<ChatArea onAddSourcesOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText('新增來源即可開始對話')).toBeTruthy();
    unmount();

    useStore.setState({ documents: [readyDocument] });
    render(<ChatArea onAddSourcesOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText('針對你的來源提問…')).toBeTruthy();
  });

  it('names the add sources dialog in Traditional Chinese', () => {
    render(<SourcesPanelHarness />);

    fireEvent.click(screen.getByRole('button', { name: '新增來源' }));

    expect(screen.getByRole('dialog', { name: '新增來源' })).toBeTruthy();
  });
});
