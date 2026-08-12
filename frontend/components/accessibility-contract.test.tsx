// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatArea from './chat/ChatArea';
import ConversationList from './ConversationList';
import DocumentPreview from './DocumentPreview';
import ExportDialog from './ExportDialog';
import FileUpload from './FileUpload';
import MarkdownRenderer from './MarkdownRenderer';
import TopNav from './layout/TopNav';
import SourcesPanel from './layout/SourcesPanel';
import ProjectDialog from './ProjectDialog';
import Settings from './Settings';
import useStore from '@/store/useStore';
import LoginPage from '@/app/login/page';
import type { Conversation, Document, Project } from '@/lib/api';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const workspaceIconButtonNames = [
  '\u901a\u77e5',
  '\u8aaa\u660e',
  '\u8a2d\u5b9a',
  '\u4f7f\u7528\u8005\u9078\u55ae',
  '\u9644\u52a0\u6a94\u6848',
  '\u50b3\u9001\u8a0a\u606f',
];
const openProjectDialog = '\u958b\u555f\u5efa\u7acb\u5c08\u6848\u5c0d\u8a71\u6846';
const closeProjectDialog = '\u95dc\u9589\u5efa\u7acb\u65b0\u5c08\u6848\u5c0d\u8a71\u6846';
const initialStoreState = useStore.getState();
const project: Project = {
  id: 'project-1',
  name: 'Accessibility Project',
  description: null,
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};
const previewDocument: Document = {
  id: 'document-1',
  name: 'Accessibility Notes',
  type: 'text',
  content: 'Document content',
  meta: {},
  status: 'ready',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  chunk_count: 1,
};
const externalPreviewDocument: Document = {
  ...previewDocument,
  id: 'external-document-1',
  name: 'External Accessibility Notes',
  type: 'url',
  url: 'https://example.com',
};
const conversation: Conversation = {
  id: 'conversation-1',
  project_id: project.id,
  title: 'Accessibility Conversation',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  message_count: 1,
};

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function ProjectDialogHarness() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>{openProjectDialog}</button>
      <ProjectDialog isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}

function SettingsHarness() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>Open settings</button>
      <Settings isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}

function DocumentPreviewHarness() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>Open document preview</button>
      {isOpen && <DocumentPreview document={previewDocument} onClose={() => setIsOpen(false)} />}
    </>
  );
}

function ExportDialogHarness() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>Open export</button>
      {isOpen && <ExportDialog type="conversation" id="conversation-1" name="Conversation" onClose={() => setIsOpen(false)} />}
    </>
  );
}

const configureSourcesStore = (documents: Document[] = []) => {
  useStore.setState({
    currentProject: project,
    projects: [project],
    documents,
    fetchProjects: async () => {},
  });
};

const dialogTitleIds = (dialogs: HTMLElement[]) => dialogs.map((dialog) => (
  dialog.getAttribute('aria-labelledby')
));

describe('workspace accessibility contract', () => {
  it('gives every confirmed icon-only workspace control a Traditional Chinese accessible name', () => {
    render(
      <>
        <TopNav />
        <ChatArea />
      </>,
    );

    workspaceIconButtonNames.forEach((name) => {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    });
  });

  it('makes the project dialog a named modal and returns focus to its trigger after Escape', () => {
    render(<ProjectDialogHarness />);

    const trigger = screen.getByRole('button', { name: openProjectDialog });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'Create New Project' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Project Name *' }));
    expect(screen.getByRole('button', { name: closeProjectDialog })).toBeTruthy();

    fireEvent.keyDown(dialog, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('gives the remaining active modal components named modal semantics', () => {
    render(
      <>
        <DocumentPreview document={previewDocument} onClose={() => {}} />
        <ExportDialog type="conversation" id="conversation-1" name="Conversation" onClose={() => {}} />
        <Settings isOpen onClose={() => {}} />
      </>,
    );

    ['Accessibility Notes', 'Export Conversation', 'Settings'].forEach((name) => {
      const dialog = screen.getByRole('dialog', { name });
      expect(dialog.getAttribute('aria-modal')).toBe('true');
    });
  });

  it('gives the sources upload modal named modal semantics', () => {
    configureSourcesStore();
    render(<SourcesPanel />);

    const trigger = screen.getByRole('button', { name: 'Add Source' });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'Add Sources' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('button', {
      name: '\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846',
    }));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Add Sources' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('keeps settings open while saving when Escape is pressed', () => {
    render(<SettingsHarness />);

    const trigger = screen.getByRole('button', { name: 'Open settings' });
    trigger.focus();
    fireEvent.click(trigger);

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    const dialog = screen.getByRole('dialog', { name: 'Settings' });
    expect(screen.getByRole('button', { name: '\u95dc\u9589\u8a2d\u5b9a\u5c0d\u8a71\u6846' }).hasAttribute('disabled')).toBe(true);

    fireEvent.keyDown(dialog, { key: 'Escape' });

    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy();
  });

  it('blocks the settings cancel action while saving', () => {
    render(<SettingsHarness />);

    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    const cancelButton = screen.getByRole('button', { name: 'Cancel' });
    expect(cancelButton.hasAttribute('disabled')).toBe(true);

    fireEvent.click(cancelButton);

    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy();
  });

  it('traps Tab and Shift+Tab between the first and last enabled controls in a dialog', () => {
    render(<ProjectDialogHarness />);

    fireEvent.click(screen.getByRole('button', { name: openProjectDialog }));
    const closeButton = screen.getByRole('button', { name: closeProjectDialog });
    const cancelButton = screen.getByRole('button', { name: 'Cancel' });

    closeButton.focus();
    fireEvent.keyDown(closeButton, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(cancelButton);

    cancelButton.focus();
    fireEvent.keyDown(cancelButton, { key: 'Tab' });
    expect(document.activeElement).toBe(closeButton);
  });

  it('keeps focus inside a Project dialog while creation disables every control', async () => {
    let resolveProject: (value: Project) => void;
    useStore.setState({
      createProject: () => new Promise<Project>((resolve) => {
        resolveProject = resolve;
      }),
      selectProject: () => {},
    });
    render(
      <>
        <button>Background control</button>
        <ProjectDialogHarness />
      </>,
    );

    const trigger = screen.getByRole('button', { name: openProjectDialog });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole('textbox', { name: 'Project Name *' }), {
      target: { value: 'Busy project' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));

    const dialog = screen.getByRole('dialog', { name: 'Create New Project' });
    await waitFor(() => expect(screen.getByRole('button', { name: closeProjectDialog }).hasAttribute('disabled')).toBe(true));
    screen.getByRole('button', { name: 'Background control' }).focus();
    fireEvent.keyDown(document, { key: 'Tab' });

    expect(document.activeElement).toBe(dialog);
    resolveProject!(project);
  });

  it('limits Escape and focus restoration to the topmost nested workspace dialog', () => {
    render(<TopNav />);

    const settingsTrigger = screen.getByRole('button', { name: '\u8a2d\u5b9a' });
    settingsTrigger.focus();
    fireEvent.click(settingsTrigger);
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy();

    const projectTrigger = screen.getByRole('button', { name: '\u65b0\u589e\u5c08\u6848' });
    projectTrigger.focus();
    fireEvent.click(projectTrigger);
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Create New Project' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy();
    expect(document.activeElement).toBe(projectTrigger);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Settings' })).toBeNull();
    expect(document.activeElement).toBe(settingsTrigger);
  });

  it('hands the Tab trap to the nested dialog and back to the outer dialog on close', () => {
    render(<TopNav />);

    fireEvent.click(screen.getByRole('button', { name: '設定' }));
    const settingsClose = screen.getByRole('button', { name: '關閉設定對話框' });

    fireEvent.click(screen.getByRole('button', { name: '新增專案' }));
    const projectDialog = screen.getByRole('dialog', { name: 'Create New Project' });

    // Focus parked on an outer-dialog control must be pulled back into the nested dialog.
    settingsClose.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(projectDialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document, { key: 'Escape' });
    const settingsDialog = screen.getByRole('dialog', { name: 'Settings' });

    // With the nested dialog gone, the outer dialog owns the trap again.
    screen.getByRole('button', { name: 'Save Changes' }).focus();
    fireEvent.keyDown(document, { key: 'Tab' });

    expect(settingsDialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'General' }));
  });

  it('uses distinct heading ids for every Project, DocumentPreview, Export, and Settings instance', () => {
    render(
      <>
        <ProjectDialog isOpen onClose={() => {}} />
        <ProjectDialog isOpen onClose={() => {}} />
        <DocumentPreview document={previewDocument} onClose={() => {}} />
        <DocumentPreview document={previewDocument} onClose={() => {}} />
        <ExportDialog type="conversation" id="conversation-1" name="Conversation" onClose={() => {}} />
        <ExportDialog type="conversation" id="conversation-2" name="Conversation" onClose={() => {}} />
        <Settings isOpen onClose={() => {}} />
        <Settings isOpen onClose={() => {}} />
      </>,
    );

    const ids = dialogTitleIds(screen.getAllByRole('dialog'));
    expect(new Set(ids).size).toBe(ids.length);
    ids.forEach((id) => expect(document.getElementById(id || '')).toBeTruthy());
  });

  it('uses a distinct heading id for each sources upload dialog instance', () => {
    configureSourcesStore();
    render(
      <>
        <SourcesPanel />
        <SourcesPanel />
      </>,
    );

    const triggers = screen.getAllByRole('button', { name: 'Add Source' });
    fireEvent.click(triggers[0]);
    const firstId = screen.getByRole('dialog', { name: 'Add Sources' }).getAttribute('aria-labelledby');
    fireEvent.click(screen.getByRole('button', { name: '\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846' }));

    fireEvent.click(triggers[1]);
    const secondId = screen.getByRole('dialog', { name: 'Add Sources' }).getAttribute('aria-labelledby');

    expect(firstId).not.toBe(secondId);
    expect(document.getElementById(secondId || '')).toBeTruthy();
  });

  it('gives every active dialog initial focus, Escape dismissal, and focus restoration', () => {
    const cases = [
      {
        Harness: ProjectDialogHarness,
        trigger: openProjectDialog,
        dialog: 'Create New Project',
        initialRole: 'textbox',
        initialFocus: 'Project Name *',
      },
      {
        Harness: DocumentPreviewHarness,
        trigger: 'Open document preview',
        dialog: 'Accessibility Notes',
        initialRole: 'button',
        initialFocus: '\u95dc\u9589\u6587\u4ef6\u9810\u89bd\u5c0d\u8a71\u6846',
      },
      {
        Harness: ExportDialogHarness,
        trigger: 'Open export',
        dialog: 'Export Conversation',
        initialRole: 'radio',
        initialFocus: /markdown/i,
      },
      {
        Harness: SettingsHarness,
        trigger: 'Open settings',
        dialog: 'Settings',
        initialRole: 'button',
        initialFocus: '\u95dc\u9589\u8a2d\u5b9a\u5c0d\u8a71\u6846',
      },
    ];

    cases.forEach(({ Harness, trigger: triggerName, dialog: dialogName, initialRole, initialFocus }) => {
      const view = render(<Harness />);
      const trigger = screen.getByRole('button', { name: triggerName });
      trigger.focus();
      fireEvent.click(trigger);

      expect(screen.getByRole('dialog', { name: dialogName })).toBeTruthy();
      expect(document.activeElement).toBe(screen.getByRole(initialRole, { name: initialFocus }));

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByRole('dialog', { name: dialogName })).toBeNull();
      expect(document.activeElement).toBe(trigger);
      view.unmount();
    });
  });

  it('restores focus to the real sources trigger that opens the document preview', () => {
    configureSourcesStore([previewDocument]);
    render(<SourcesPanel />);

    const previewTrigger = screen.getByRole('button', { name: '預覽文件' });
    previewTrigger.focus();
    fireEvent.click(previewTrigger);

    expect(screen.getByRole('dialog', { name: 'Accessibility Notes' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Accessibility Notes' })).toBeNull();
    expect(document.activeElement).toBe(previewTrigger);
  });

  it('restores focus to the real top navigation trigger that opens the export dialog', () => {
    useStore.setState({
      currentProject: project,
      projects: [project],
      currentConversation: conversation,
      conversations: [conversation],
    });
    render(<TopNav />);

    const exportTrigger = screen.getByRole('button', { name: '匯出內容' });
    exportTrigger.focus();
    fireEvent.click(exportTrigger);

    expect(screen.getByRole('dialog', { name: 'Export Conversation' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Export Conversation' })).toBeNull();
    expect(document.activeElement).toBe(exportTrigger);
  });

  it('restores sources upload state after a successful real URL upload so reopening is dismissible', async () => {
    const fetchResponse = (body: unknown) => new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
    let resolveUpload: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = input.toString();
      if (url.includes('/upload-url')) {
        return new Promise<Response>((resolve) => {
          resolveUpload = resolve;
        });
      }
      if (url.includes('/docs/uploaded-document')) {
        return fetchResponse({
          id: 'uploaded-document',
          title: 'https://example.com',
          source_type: 'url',
          source_url: 'https://example.com',
          meta_json: {},
          status: 'queued',
          error_message: null,
          created_at: '2026-08-12T00:00:00Z',
          updated_at: '2026-08-12T00:00:00Z',
          chunk_count: 0,
        });
      }
      return fetchResponse([]);
    }));
    configureSourcesStore();
    render(<SourcesPanel />);

    const trigger = screen.getByRole('button', { name: 'Add Source' });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('button', { name: 'URL' }));
    fireEvent.change(screen.getByPlaceholderText('Enter website URL...'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(
      screen.getByRole('button', { name: '\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846' }).hasAttribute('disabled'),
    ).toBe(true));
    resolveUpload!(fetchResponse({ doc_id: 'uploaded-document', status: 'queued', message: 'accepted' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add Sources' })).toBeNull());
    expect(useStore.getState().currentProject).toBe(project);

    fireEvent.click(trigger);
    const closeButton = screen.getByRole('button', { name: '\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846' });
    expect(closeButton.hasAttribute('disabled')).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(closeButton));
  });

  it('reports the upload busy state before delegating to the parent upload handler', async () => {
    const events: string[] = [];
    let resolveUpload: () => void;
    const inFlight = new Promise<void>((resolve) => {
      resolveUpload = resolve;
    });

    render(
      <FileUpload
        onUpload={async () => {
          events.push('onUpload');
          await inFlight;
        }}
        onUploadingChange={(isUploading) => events.push(`busy:${isUploading}`)}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'URL' }));
    fireEvent.change(screen.getByPlaceholderText('Enter website URL...'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(events).toEqual(['busy:true', 'onUpload']);

    resolveUpload!();

    await waitFor(() => expect(events).toEqual(['busy:true', 'onUpload', 'busy:false']));
  });

  it('covers the accessible names of every active icon control added to the workspace', () => {
    configureSourcesStore([previewDocument]);
    render(
      <>
        <TopNav />
        <ChatArea />
        <SourcesPanel />
        <DocumentPreview document={previewDocument} onClose={() => {}} />
        <FileUpload onUpload={async () => {}} />
      </>,
    );

    [
      '\u65b0\u589e\u5c08\u6848', '\u532f\u51fa\u5167\u5bb9', '\u5207\u63db\u4e3b\u984c', '\u901a\u77e5', '\u8aaa\u660e', '\u8a2d\u5b9a', '\u4f7f\u7528\u8005\u9078\u55ae',
      '\u9644\u52a0\u6a94\u6848', '\u50b3\u9001\u8a0a\u606f', '\u9810\u89bd\u6587\u4ef6', '\u522a\u9664\u6587\u4ef6', '\u8907\u88fd\u5167\u5bb9', '\u4e0b\u8f09\u6587\u4ef6', '\u5207\u63db\u5168\u87a2\u5e55', '\u95dc\u9589\u6587\u4ef6\u9810\u89bd\u5c0d\u8a71\u6846',
    ].forEach((name) => expect(screen.getByRole('button', { name })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('browse'), {
      target: { files: [new File(['pdf'], 'paper.pdf', { type: 'application/pdf' })] },
    });
    expect(screen.getByRole('button', { name: '\u79fb\u9664\u6a94\u6848' })).toBeTruthy();
  });

  it('names the sources project selector', () => {
    configureSourcesStore();
    render(<SourcesPanel />);

    expect(screen.getByRole('combobox', { name: '選擇專案' })).toBeTruthy();
  });

  it('associates every settings select with its visible label', () => {
    render(<Settings isOpen onClose={() => {}} />);

    expect(screen.getByRole('combobox', { name: 'Language' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'API Keys' }));

    expect(screen.getByRole('combobox', { name: 'Model' })).toBeTruthy();
  });

  it('names the conversation list icon controls, including the rename lifecycle', () => {
    useStore.setState({
      currentProject: project,
      projects: [project],
      conversations: [conversation],
    });
    render(<ConversationList />);

    [
      '摺疊對話清單',
      '新增對話',
      '重新命名對話',
      '刪除對話',
    ].forEach((name) => expect(screen.getByRole('button', { name })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: '摺疊對話清單' }));
    expect(screen.getByRole('button', { name: '展開對話清單' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '展開對話清單' }));
    fireEvent.click(screen.getByRole('button', { name: '重新命名對話' }));

    expect(screen.getByRole('button', { name: '儲存對話名稱' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '取消重新命名' })).toBeTruthy();
  });

  it('names the markdown code copy control', () => {
    render(<MarkdownRenderer content={'```ts\nconst answer = 42;\n```'} />);

    expect(screen.getByRole('button', { name: '複製程式碼' })).toBeTruthy();
  });

  it('names the login password visibility control in both states', () => {
    render(<LoginPage />);

    const reveal = screen.getByRole('button', { name: '顯示密碼' });
    fireEvent.click(reveal);

    expect(screen.getByRole('button', { name: '隱藏密碼' })).toBeTruthy();
  });

  it('keeps the document preview frame inside the dialog tab cycle', () => {
    render(<DocumentPreview document={externalPreviewDocument} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog', { name: 'External Accessibility Notes' });
    const frame = dialog.querySelector('iframe');
    const copyButton = screen.getByRole('button', { name: '複製內容' });

    copyButton.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });

    expect(document.activeElement).toBe(frame);
  });

  it('names conditional DocumentPreview external-link and Export close icon controls', () => {
    render(
      <>
        <DocumentPreview document={externalPreviewDocument} onClose={() => {}} />
        <ExportDialog type="conversation" id="conversation-1" name="Conversation" onClose={() => {}} />
      </>,
    );

    expect(screen.getByRole('button', { name: '\u5728\u65b0\u5206\u9801\u958b\u555f' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '\u95dc\u9589\u532f\u51fa\u5c0d\u8a71\u6846' })).toBeTruthy();
  });
});
