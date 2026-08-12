// @vitest-environment jsdom

import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import Home from '@/app/page';
import {
  desktopWorkspaceReducer,
  getDesktopWorkspaceStyle,
  initialDesktopWorkspaceState,
  resolveDesktopWorkspaceMetrics,
} from '@/components/desktopLayout';
import type { Conversation, Document, Project } from '@/lib/api';
import useStore from '@/store/useStore';

const originalStoreState = useStore.getState();
const project: Project = {
  id: 'project-1',
  name: '版面測試專案',
  description: null,
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 2,
  conversation_count: 1,
};
const documents: Document[] = [
  {
    id: 'document-1',
    name: '第一份資料',
    type: 'text',
    content: '第一份內容',
    meta: {},
    status: 'ready',
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
    chunk_count: 1,
  },
  {
    id: 'document-2',
    name: '第二份資料',
    type: 'text',
    content: '第二份內容',
    meta: {},
    status: 'ready',
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
    chunk_count: 1,
  },
];
const conversation: Conversation = {
  id: 'conversation-1',
  project_id: project.id,
  title: '版面測試對話',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  message_count: 0,
};

function configureWorkspaceStore() {
  useStore.setState({
    ...originalStoreState,
    projects: [project],
    currentProject: project,
    loadingProjects: false,
    documents,
    loadingDocuments: false,
    uploadProgress: {},
    conversations: [conversation],
    currentConversation: conversation,
    messages: [],
    loadingConversations: false,
    loadingMessages: false,
    fetchProjects: vi.fn(async () => undefined),
    selectProject: vi.fn(),
    createProject: vi.fn(async () => project),
    deleteProject: vi.fn(async () => undefined),
    fetchDocuments: vi.fn(async () => undefined),
    uploadDocument: vi.fn(async () => undefined),
    createDocument: vi.fn(async () => undefined),
    deleteDocument: vi.fn(async () => undefined),
    fetchConversations: vi.fn(async () => undefined),
    selectConversation: vi.fn(async () => undefined),
    createConversation: vi.fn(async () => conversation),
    updateConversation: vi.fn(async () => undefined),
    deleteConversation: vi.fn(async () => undefined),
    fetchMessages: vi.fn(async () => undefined),
    sendQuery: vi.fn(async () => undefined),
    toggleSidebar: vi.fn(),
    toggleStudio: vi.fn(),
    reset: vi.fn(),
  }, true);
}

beforeEach(() => {
  configureWorkspaceStore();
});

afterEach(() => {
  cleanup();
  useStore.setState(originalStoreState, true);
  vi.restoreAllMocks();
});

describe('desktop workspace layout', () => {
  test.each([
    [1024, 192, 456, 184, 192],
    [1440, 216, 820.8, 187.2, 216],
    [1920, 272, 1152, 224, 272],
  ])(
    'keeps a usable dominant center and bounded conversation track at %ipx',
    (viewportWidth, sources, center, conversations, studio) => {
      const metrics = resolveDesktopWorkspaceMetrics(
        viewportWidth,
        initialDesktopWorkspaceState,
      );

      expect(metrics.sources).toBeCloseTo(sources);
      expect(metrics.center).toBeCloseTo(center);
      expect(metrics.conversations).toBeCloseTo(conversations);
      expect(metrics.studio).toBeCloseTo(studio);
      expect(metrics.total).toBeCloseTo(viewportWidth);
      expect(metrics.center).toBeGreaterThan(
        Math.max(metrics.sources, metrics.conversations, metrics.studio),
      );
      expect(metrics.center).toBeGreaterThanOrEqual(448);
      expect(metrics.conversations).toBeGreaterThanOrEqual(184);
      expect(metrics.conversations).toBeLessThanOrEqual(224);
    },
  );

  test('renders center-relative welcome sizing through the production DOM contract', () => {
    const { container } = render(createElement(Home));
    const workspace = container.querySelector<HTMLElement>(
      '[data-layout="desktop-workspace"]',
    );
    const chat = container.querySelector<HTMLElement>(
      '[data-layout="chat-workspace"]',
    );
    const hero = container.querySelector<HTMLElement>(
      '[data-layout="welcome-hero"]',
    );
    const icon = container.querySelector<HTMLElement>(
      '[data-layout="welcome-icon"]',
    );
    const actions = container.querySelector<HTMLElement>(
      '[data-layout="welcome-actions"]',
    );
    const title = screen.getByRole('heading', {
      name: '新增來源即可開始使用',
    });

    expect(workspace?.style.gridTemplateColumns).toBe(
      getDesktopWorkspaceStyle(initialDesktopWorkspaceState).gridTemplateColumns,
    );
    expect(chat?.style.containerType).toBe('inline-size');
    expect(hero?.style.maxWidth).toBe('60rem');
    expect(icon?.style.width).toContain('cqw');
    expect(title.style.fontSize).toContain('cqw');
    expect(actions?.style.gap).toContain('cqw');
  });

  test('collapses and restores Sources through Home without losing local state or focus', () => {
    const { container } = render(createElement(Home));
    const workspace = container.querySelector<HTMLElement>(
      '[data-layout="desktop-workspace"]',
    );
    const sources = screen.getByRole('complementary', { name: '來源' });
    const content = screen.getByRole('region', {
      name: '來源面板內容',
      hidden: true,
    });
    const search = screen.getByRole('textbox', {
      name: '搜尋來源',
    }) as HTMLInputElement;
    const toggle = screen.getByRole('button', { name: '收合來源' });
    const expandedColumns = workspace?.style.gridTemplateColumns;

    fireEvent.change(search, { target: { value: '第二' } });
    expect(screen.queryByText('第一份資料')).toBeNull();
    expect(screen.getByText('第二份資料')).toBeTruthy();

    toggle.focus();
    fireEvent.click(toggle);

    expect(sources.getAttribute('data-panel-state')).toBe('collapsed');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-controls')).toBe(content.id);
    expect(content.hidden).toBe(true);
    expect(document.activeElement).toBe(toggle);
    expect(workspace?.style.gridTemplateColumns).not.toBe(expandedColumns);
    expect(search.value).toBe('第二');

    fireEvent.click(toggle);

    expect(sources.getAttribute('data-panel-state')).toBe('expanded');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(content.hidden).toBe(false);
    expect(document.activeElement).toBe(toggle);
    expect(workspace?.style.gridTemplateColumns).toBe(expandedColumns);
    expect(screen.getByRole('textbox', { name: '搜尋來源' })).toBe(search);
    expect(search.value).toBe('第二');
  });

  test('drives the Studio collapse callback and restores the same focused control', () => {
    render(createElement(Home));
    const studio = screen.getByRole('complementary', { name: '工作室' });
    const content = screen.getByRole('region', {
      name: '工作室面板內容',
      hidden: true,
    });
    const toggle = screen.getByRole('button', { name: '收合工作室' });

    toggle.focus();
    fireEvent.click(toggle);

    expect(studio.getAttribute('data-panel-state')).toBe('collapsed');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-controls')).toBe(content.id);
    expect(content.hidden).toBe(true);
    expect(document.activeElement).toBe(toggle);

    fireEvent.click(toggle);

    expect(studio.getAttribute('data-panel-state')).toBe('expanded');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(content.hidden).toBe(false);
    expect(document.activeElement).toBe(toggle);
  });

  test('uses a compact Traditional Chinese conversation header contract', () => {
    render(createElement(Home));

    expect(screen.getByRole('heading', { name: '對話' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '收合對話' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '新增對話' })).toHaveLength(2);
  });

  test('releases center width when supporting panels collapse', () => {
    const collapsedState = desktopWorkspaceReducer(
      desktopWorkspaceReducer(initialDesktopWorkspaceState, {
        type: 'toggle-panel',
        panel: 'sources',
      }),
      { type: 'toggle-panel', panel: 'studio' },
    );
    const expanded = resolveDesktopWorkspaceMetrics(
      1024,
      initialDesktopWorkspaceState,
    );
    const collapsed = resolveDesktopWorkspaceMetrics(1024, collapsedState);

    expect(collapsed.sources).toBe(48);
    expect(collapsed.studio).toBe(48);
    expect(collapsed.center).toBe(744);
    expect(collapsed.center).toBeGreaterThan(expanded.center);
    expect(collapsed.total).toBe(1024);
  });
});
