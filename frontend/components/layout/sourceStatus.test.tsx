// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import SourcesPanel from './SourcesPanel';
import ProjectDialogProvider from '../ProjectDialogProvider';
import useStore from '@/store/useStore';
import type { Document, DocumentStatus, Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
  role: 'owner',
};


function documentWith(status: DocumentStatus, error_message?: string): Document {
  return {
    id: `document-${status}`,
    name: `Example ${status}`,
    type: 'url',
    isOwnedByCaller: true,
    url: 'https://example.com',
    meta: {},
    status,
    error_message,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
    chunk_count: 0,
  };
}

function renderPanel() {
  render(
    <ProjectDialogProvider>
      <SourcesPanel isAddSourcesOpen={false} onAddSourcesOpenChange={() => {}} />
    </ProjectDialogProvider>,
  );
}

beforeEach(() => {
  useStore.setState({
    projects: [project],
    currentProject: project,
    loadingDocuments: false,
    fetchDocuments: async () => undefined,
    fetchProjects: async () => undefined,
  });
});

afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
});

describe('source status', () => {
  it('names every status a reader can hit instead of showing the raw value', () => {
    useStore.setState({ documents: [documentWith('queued')] });
    renderPanel();
    expect(screen.getByText('Queued')).toBeTruthy();
    cleanup();

    // Indexing now happens while the document is still processing, so this is
    // the state a freshly uploaded source sits in until it is retrievable.
    useStore.setState({ documents: [documentWith('processing')] });
    renderPanel();
    expect(screen.getByText('Processing...')).toBeTruthy();
    cleanup();

    useStore.setState({ documents: [documentWith('transcribing' as DocumentStatus)] });
    renderPanel();
    expect(screen.getByText('Transcribing...')).toBeTruthy();
    cleanup();

    useStore.setState({ documents: [documentWith('ready')] });
    renderPanel();
    expect(screen.getByText('Ready')).toBeTruthy();
  });

  it('says a failed source failed, and why', () => {
    useStore.setState({
      documents: [
        documentWith('error', 'No searchable text could be extracted, so this source cannot be queried.'),
      ],
    });
    renderPanel();

    expect(screen.getByText('Failed')).toBeTruthy();
    expect(screen.getByText(/No searchable text could be extracted/)).toBeTruthy();
    expect(screen.queryByText('error')).toBeNull();
  });

  it('still says a source failed when the backend gave no reason', () => {
    useStore.setState({ documents: [documentWith('error')] });
    renderPanel();

    expect(screen.getByText('Failed')).toBeTruthy();
  });

  it('leaves failed sources unchecked and out of the selection count', () => {
    useStore.setState({
      documents: [documentWith('ready'), documentWith('error', 'No captions.')],
    });
    renderPanel();

    expect(screen.getByText('1 of 1 selected')).toBeTruthy();
    expect(screen.getByRole('checkbox', {
      name: 'Use Example ready in answers and Studio',
    })).toHaveProperty('checked', true);
    expect(screen.getByRole('checkbox', {
      name: 'Use Example error in answers and Studio',
    })).toHaveProperty('checked', false);
    expect(screen.getByRole('checkbox', {
      name: 'Use Example error in answers and Studio',
    })).toHaveProperty('disabled', true);
  });
});
