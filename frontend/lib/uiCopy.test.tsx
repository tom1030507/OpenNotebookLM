import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { getWorkspaceState, setWorkspaceState } = vi.hoisted(() => {
  let workspaceState: Record<string, unknown> = {};
  return {
    getWorkspaceState: () => workspaceState,
    setWorkspaceState: (nextState: Record<string, unknown>) => {
      workspaceState = nextState;
    },
  };
});

vi.mock('@/store/useStore', () => ({
  default: () => getWorkspaceState(),
}));

import ConversationList from '@/components/ConversationList';
import DocumentPreview from '@/components/DocumentPreview';
import ExportDialog from '@/components/ExportDialog';
import MarkdownRenderer from '@/components/MarkdownRenderer';
import ChatArea from '@/components/chat/ChatArea';
import SourcesPanel from '@/components/layout/SourcesPanel';
import type { Document, Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: '研究筆記',
  description: null,
  meta_json: {},
  document_count: 1,
  conversation_count: 1,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
};

const document = (type: Document['type'], status: Document['status'] = 'ready'): Document => ({
  id: `${type}-1`,
  name: type === 'youtube' ? '影片資料' : 'paper.pdf',
  type,
  url: type === 'url' ? 'https://example.com' : type === 'youtube' ? 'https://youtu.be/video-id' : undefined,
  content: type === 'text' ? '文件內容' : type === 'youtube' ? '影片逐字稿' : undefined,
  meta: {},
  status,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  chunk_count: 1,
});

const emptyWorkspaceState = {
  projects: [],
  currentProject: null,
  documents: [],
  loadingDocuments: false,
  conversations: [],
  currentConversation: null,
  messages: [],
  fetchProjects: vi.fn(),
  selectProject: vi.fn(),
  createProject: vi.fn(),
  uploadDocument: vi.fn(),
  createDocument: vi.fn(),
  deleteDocument: vi.fn(),
  sendQuery: vi.fn(),
  createConversation: vi.fn(),
  updateConversation: vi.fn(),
  deleteConversation: vi.fn(),
};

afterEach(() => {
  setWorkspaceState(emptyWorkspaceState);
  vi.restoreAllMocks();
});

describe('Traditional Chinese workspace copy', () => {
  it('renders initial workspace labels and empty states in Traditional Chinese', () => {
    setWorkspaceState({ ...emptyWorkspaceState, currentProject: null, documents: [], conversations: [], messages: [] });
    const markup = renderToStaticMarkup(
      <>
        <SourcesPanel />
        <ChatArea />
        <ConversationList />
      </>,
    );

    expect(markup).toContain('資料來源');
    expect(markup).toContain('選擇或建立專案以開始使用');
    expect(markup).toContain('新增資料來源後即可開始對話');
    expect(markup).not.toContain('Sources');
  });

  it('renders project-selected ready, citation, and missing-title states in Traditional Chinese', () => {
    const readyDocument = document('pdf');
    setWorkspaceState({
      ...emptyWorkspaceState,
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      conversations: [{
        id: 'conversation-1',
        project_id: project.id,
        title: '未命名對話',
        created_at: '2026-08-12T00:00:00Z',
        updated_at: '2026-08-12T00:00:00Z',
        message_count: 1,
      }],
      messages: [{
        id: 'message-1',
        conversation_id: 'conversation-1',
        role: 'assistant',
        content: '摘要內容',
        created_at: '2026-08-12T00:00:00Z',
        citations: [{ source: '未知來源', page: 4 }],
      }],
    });
    const markup = renderToStaticMarkup(
      <>
        <SourcesPanel />
        <ChatArea />
        <ConversationList />
      </>,
    );

    expect(markup).toContain('已就緒');
    expect(markup).toContain('針對資料來源提出任何問題...');
    expect(markup).toContain('未命名對話');
    expect(markup).toContain('未知來源');
    expect(markup).toContain('資料來源：');
    expect(markup).not.toMatch(/>Ready<|>Processing<|>Unknown source<|>Untitled Conversation</);
  });

  it.each([
    ['pdf', 'PDF'],
    ['url', 'URL'],
    ['youtube', 'YouTube'],
    ['text', '文字'],
  ] as const)('renders the %s document type with its user-facing label', (type, label) => {
    const markup = renderToStaticMarkup(
      <DocumentPreview document={document(type)} onClose={() => undefined} />,
    );

    expect(markup).toContain(`${label} · 已就緒`);
    expect(markup).not.toContain(`${type.toUpperCase()} · ready`);
  });

  it('renders the processing document status in Traditional Chinese', () => {
    const markup = renderToStaticMarkup(
      <DocumentPreview document={document('pdf', 'processing')} onClose={() => undefined} />,
    );

    expect(markup).toContain('PDF · 處理中...');
    expect(markup).not.toContain('PDF · Processing');
  });

  it.each([
    ['queued', '等待處理中', 'Queued'],
    ['error', '處理失敗', 'Error'],
  ] as const)('renders the %s document status in Traditional Chinese', (status, label, englishLabel) => {
    const markup = renderToStaticMarkup(
      <DocumentPreview document={document('pdf', status)} onClose={() => undefined} />,
    );

    expect(markup).toContain(`PDF · ${label}`);
    expect(markup).not.toContain(`PDF · ${englishLabel}`);
  });

  it('renders the code-copy control in Traditional Chinese', () => {
    const codeMarkup = renderToStaticMarkup(<MarkdownRenderer content={'```ts\nconst answer = 42;\n```'} />);

    expect(codeMarkup).toContain('複製程式碼');
    expect(codeMarkup).not.toContain('Copy code');
  });

  it('renders the natural Traditional Chinese export description', () => {
    const markup = renderToStaticMarkup(
      <ExportDialog type="conversation" id="conversation-1" name="研究筆記" onClose={() => undefined} />,
    );

    expect(markup).toContain('以偏好的格式匯出「研究筆記」');
    expect(markup).not.toContain('根據您的偏好匯出');
  });
});
