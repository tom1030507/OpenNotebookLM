import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import ConversationList from '@/components/ConversationList';
import DocumentPreview from '@/components/DocumentPreview';
import ExportDialog from '@/components/ExportDialog';
import FileUpload from '@/components/FileUpload';
import ProjectDialog from '@/components/ProjectDialog';
import Settings from '@/components/Settings';
import ChatArea from '@/components/chat/ChatArea';
import SourcesPanel from '@/components/layout/SourcesPanel';
import StudioPanel from '@/components/layout/StudioPanel';
import TopNav from '@/components/layout/TopNav';
import useStore from '@/store/useStore';

const initialState = useStore.getState();

afterEach(() => {
  useStore.setState(initialState, true);
});

describe('Traditional Chinese workspace copy', () => {
  it('renders the confirmed workspace copy in Traditional Chinese', () => {
    const project = {
      id: 'project-1',
      name: '研究筆記',
      description: '',
      document_count: 1,
      conversation_count: 1,
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    };
    const document = {
      id: 'document-1',
      name: 'paper.pdf',
      type: 'pdf' as const,
      status: 'processing' as const,
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    };

    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [document],
      conversations: [{
        id: 'conversation-1',
        project_id: 'project-1',
        title: '研究對話',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        message_count: 1,
      }],
      currentConversation: null,
      messages: [{
        id: 'message-1',
        conversation_id: 'conversation-1',
        role: 'assistant',
        content: '摘要內容',
        citations: [],
        created_at: '2026-08-12T00:00:00Z',
      }],
    });

    const markup = renderToStaticMarkup(React.createElement(
      React.Fragment,
      null,
      React.createElement(TopNav),
      React.createElement(SourcesPanel),
      React.createElement(ChatArea),
      React.createElement(ConversationList),
      React.createElement(StudioPanel),
      React.createElement(ProjectDialog, { isOpen: true, onClose: () => undefined }),
      React.createElement(FileUpload, { onUpload: async () => undefined }),
      React.createElement(DocumentPreview, { document, onClose: () => undefined }),
      React.createElement(ExportDialog, {
        type: 'project',
        id: 'project-1',
        name: '研究筆記',
        onClose: () => undefined,
      }),
      React.createElement(Settings, { isOpen: true, onClose: () => undefined }),
    ));

    expect(markup).toContain('資料來源');
    expect(markup).toContain('新增專案');
    expect(markup).toContain('新增資料來源後即可開始對話');
    expect(markup).toContain('處理中...');
    expect(markup).toContain('建立專案');
    expect(markup).toContain('選取檔案');
    expect(markup).toContain('匯出');
    expect(markup).toContain('設定');
    expect(markup).toContain('工作室');
    expect(markup).not.toMatch(/>Sources<|title="New Project"|placeholder="Search sources"|>New Conversation<|>Create Project<|>Select files<|>Export Project<|>Settings</i);
  });
});
