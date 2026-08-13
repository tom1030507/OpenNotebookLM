// @vitest-environment jsdom

import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import useDocumentStatusWatch, { MAX_POLLS, POLL_INTERVAL_MS } from './useDocumentStatusWatch';
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
};

const initialState = useStore.getState();

function documentWith(status: DocumentStatus, id = 'document-1'): Document {
  return {
    id,
    name: 'Example Domain',
    type: 'url',
    meta: {},
    status,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
    chunk_count: 0,
  };
}

function Watcher() {
  useDocumentStatusWatch();
  return null;
}

const advance = async (ms: number) => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};

beforeEach(() => {
  vi.useFakeTimers();
  useStore.setState({ currentProject: project, projects: [project], documents: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  useStore.setState(initialState, true);
});

describe('useDocumentStatusWatch', () => {
  it('re-checks a source that is still being indexed', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({ documents: [documentWith('processing')], refreshDocuments });
    render(<Watcher />);

    expect(refreshDocuments).not.toHaveBeenCalled();
    await advance(POLL_INTERVAL_MS);
    expect(refreshDocuments).toHaveBeenCalledWith('project-1');
    await advance(POLL_INTERVAL_MS * 2);
    expect(refreshDocuments).toHaveBeenCalledTimes(3);
  });

  it('watches a queued source too', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({ documents: [documentWith('queued')], refreshDocuments });
    render(<Watcher />);

    await advance(POLL_INTERVAL_MS);
    expect(refreshDocuments).toHaveBeenCalledTimes(1);
  });

  it('stops as soon as every source has settled', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({ documents: [documentWith('processing')], refreshDocuments });
    render(<Watcher />);

    await advance(POLL_INTERVAL_MS);
    expect(refreshDocuments).toHaveBeenCalledTimes(1);

    await act(async () => {
      useStore.setState({ documents: [documentWith('ready')] });
    });
    await advance(POLL_INTERVAL_MS * 5);
    expect(refreshDocuments).toHaveBeenCalledTimes(1);
  });

  it('never starts when the sources are already ready or failed', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({
      documents: [documentWith('ready'), documentWith('error', 'document-2')],
      refreshDocuments,
    });
    render(<Watcher />);

    await advance(POLL_INTERVAL_MS * 5);
    expect(refreshDocuments).not.toHaveBeenCalled();
  });

  it('gives up rather than polling a stuck source forever', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({ documents: [documentWith('processing')], refreshDocuments });
    render(<Watcher />);

    await advance(POLL_INTERVAL_MS * (MAX_POLLS + 20));
    expect(refreshDocuments).toHaveBeenCalledTimes(MAX_POLLS);
  });

  it('stops watching when the workspace has no project', async () => {
    const refreshDocuments = vi.fn(async () => undefined);
    useStore.setState({
      currentProject: null,
      documents: [documentWith('processing')],
      refreshDocuments,
    });
    render(<Watcher />);

    await advance(POLL_INTERVAL_MS * 3);
    expect(refreshDocuments).not.toHaveBeenCalled();
  });
});
