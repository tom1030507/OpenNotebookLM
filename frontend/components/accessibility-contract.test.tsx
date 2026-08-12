// @vitest-environment jsdom

import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ChatArea from './chat/ChatArea';
import DocumentPreview from './DocumentPreview';
import ExportDialog from './ExportDialog';
import TopNav from './layout/TopNav';
import SourcesPanel from './layout/SourcesPanel';
import ProjectDialog from './ProjectDialog';
import Settings from './Settings';
import useStore from '@/store/useStore';
import type { Document, Project } from '@/lib/api';

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

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
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
    useStore.setState({ currentProject: project, projects: [project], documents: [] });
    render(<SourcesPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }));

    const dialog = screen.getByRole('dialog', { name: 'Add Sources' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
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
});
