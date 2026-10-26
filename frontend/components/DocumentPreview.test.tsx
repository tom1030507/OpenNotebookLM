// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api, { type Citation, type Document, type Project } from '@/lib/api';
import useStore, { selectedSourceIds } from '@/store/useStore';
import DocumentPreview from './DocumentPreview';


interface BackendDocumentFixture {
  source_type: Document['type'];
  source_url: string;
  title: string;
}

/**
 * Load a document the way the app does, so the preview is exercised against a
 * URL the mapping layer produced rather than one hand-written for the test.
 */
const loadDocument = async (
  fixture: BackendDocumentFixture,
): Promise<Document> => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify([{
      id: 'document-1',
      title: fixture.title,
      source_type: fixture.source_type,
      source_url: fixture.source_url,
      meta_json: {},
      status: 'ready',
      error_message: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      chunk_count: 1,
    }]),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )));

  const [document] = await api.getDocuments('project-1');
  return document;
};


/**
 * Stand in for the object-URL API, which jsdom does not implement.
 *
 * Returns the spies so a test can assert the preview both created a URL for the
 * bytes it fetched and gave it back when it was done with it.
 */
const stubObjectUrls = () => {
  const createObjectURL = vi.fn(() => 'blob:preview-url');
  const revokeObjectURL = vi.fn();
  Object.assign(URL, { createObjectURL, revokeObjectURL });

  return { createObjectURL, revokeObjectURL };
};


afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(URL, 'createObjectURL');
  Reflect.deleteProperty(URL, 'revokeObjectURL');
});

beforeEach(() => {
  vi.spyOn(api, 'fetchDocumentGuide').mockResolvedValue({
    summary: 'A short source summary.',
    topics: [],
  });
});


describe('DocumentPreview', () => {
  it('shows processing state and retries a preview until extraction completes', async () => {
    const document = await loadDocument({
      source_type: 'docx',
      source_url: 'uploads/document-1_report.docx',
      title: 'Report',
    });
    document.status = 'queued';
    const fetchContent = vi.spyOn(api, 'fetchDocumentContent')
      .mockResolvedValueOnce('')
      .mockResolvedValueOnce('# Chapter One');
    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(await screen.findByText(/Source is still processing/)).toBeTruthy();
    expect(fetchContent).not.toHaveBeenCalled();

    screen.getByRole('button', { name: 'Check for extracted text' }).click();
    await waitFor(() => expect(fetchContent).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Source is still processing/)).toBeTruthy();

    screen.getByRole('button', { name: 'Check for extracted text' }).click();
    expect(await screen.findByText(/# Chapter One/)).toBeTruthy();
    expect(fetchContent).toHaveBeenNthCalledWith(1, 'document-1');
    expect(fetchContent).toHaveBeenNthCalledWith(2, 'document-1');
  });

  it('fetches and previews extracted text for an uploaded Office source', async () => {
    const document = await loadDocument({
      source_type: 'docx',
      source_url: 'uploads/document-1_report.docx',
      title: 'Report',
    });
    const fetchContent = vi.spyOn(api, 'fetchDocumentContent')
      .mockResolvedValue('# Chapter One\n\nReport text');

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(await screen.findByText(/# Chapter One/)).toBeTruthy();
    expect(fetchContent).toHaveBeenCalledWith('document-1');
  });

  it('fetches and previews the timestamped transcript for an audio source', async () => {
    const document = await loadDocument({
      source_type: 'mp3' as Document['type'],
      source_url: 'uploads/document-1_lecture.mp3',
      title: 'Lecture',
    });
    const fetchContent = vi.spyOn(api, 'fetchDocumentContent')
      .mockResolvedValue('## 00:00:00\nWelcome to the lecture.');

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(await screen.findByText(/## 00:00:00/)).toBeTruthy();
    expect(fetchContent).toHaveBeenCalledWith('document-1');
  });

  it('shows the in-progress notice while an audio source is transcribing', async () => {
    const document = await loadDocument({
      source_type: 'mp3' as Document['type'],
      source_url: 'uploads/document-1_lecture.mp3',
      title: 'Lecture',
    });
    document.status = 'transcribing';
    vi.spyOn(api, 'fetchDocumentContent').mockResolvedValue('');

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(
      await screen.findByText(/This document is still being processed/),
    ).toBeTruthy();
  });

  it('fetches an uploaded PDF with the session token and previews the bytes', async () => {
    // The file route requires a bearer token and a browser cannot put an
    // Authorization header on an <iframe src>, so pointing the frame straight at
    // the route would 401 into an empty pane. The bytes are fetched by the API
    // client, which does send the token, and handed over as an object URL.
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'uploads/document-1_paper.pdf',
      title: 'Paper',
    });
    const pdf = new Blob(['%PDF-1.4 preview me'], { type: 'application/pdf' });
    const fetchFile = vi.spyOn(api, 'fetchDocumentFile').mockResolvedValue(pdf);
    const { createObjectURL } = stubObjectUrls();

    render(<DocumentPreview document={document} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTitle('Paper').getAttribute('src')).toBe(
        'blob:preview-url',
      );
    });
    expect(fetchFile).toHaveBeenCalledWith('document-1');
    expect(createObjectURL).toHaveBeenCalledWith(pdf);
  });

  it('gives the object URL back when the preview closes', async () => {
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'uploads/document-1_paper.pdf',
      title: 'Paper',
    });
    vi.spyOn(api, 'fetchDocumentFile').mockResolvedValue(
      new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
    );
    const { revokeObjectURL } = stubObjectUrls();

    const { unmount } = render(
      <DocumentPreview document={document} onClose={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle('Paper')).toBeTruthy();
    });

    unmount();

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview-url');
  });

  it('says so when the file cannot be fetched, rather than showing nothing', async () => {
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'uploads/document-1_paper.pdf',
      title: 'Paper',
    });
    vi.spyOn(api, 'fetchDocumentFile').mockRejectedValue(
      new Error('Document has no stored file'),
    );
    stubObjectUrls();

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(await screen.findByText(/Document has no stored file/)).toBeTruthy();
  });

  it('loads an external PDF straight from its own address', async () => {
    // Nothing on the API guards somebody else's site, so there is no token to
    // add and no reason to proxy the bytes through the browser twice.
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'https://example.com/paper.pdf',
      title: 'External paper',
    });
    const fetchFile = vi.spyOn(api, 'fetchDocumentFile');

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(screen.getByTitle('External paper').getAttribute('src')).toBe(
      'https://example.com/paper.pdf',
    );
    expect(fetchFile).not.toHaveBeenCalled();
  });

  it('previews indexed text for a URL source and keeps its original link', async () => {
    const document = await loadDocument({
      source_type: 'url',
      source_url: 'https://example.com/article',
      title: 'Example article',
    });
    const fetchContent = vi.spyOn(api, 'fetchDocumentContent')
      .mockResolvedValue('Indexed article text');

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(await screen.findByText('Indexed article text')).toBeTruthy();
    expect(fetchContent).toHaveBeenCalledWith('document-1');
    expect(
      screen.getByRole('link', { name: 'https://example.com/article' })
        .getAttribute('href'),
    ).toBe('https://example.com/article');
    expect(screen.queryByTitle('Example article')).toBeNull();
  });

  it.each(['md', 'url'] as const)(
    'scrolls to and highlights the cited range in %s sources',
    async (sourceType) => {
    const document = await loadDocument({
      source_type: sourceType,
      source_url: sourceType === 'url'
        ? 'https://example.com/article'
        : 'https://example.com/article.md',
      title: 'Example article',
    });
    vi.spyOn(api, 'fetchDocumentContent').mockResolvedValue('First\n\nCited passage here.\n\nLast');
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    const citation: Citation = {
      source: 'Example article',
      document_id: 'document-1',
      start_offset: 7,
      end_offset: 26,
    };

    render(<DocumentPreview document={document} citation={citation} onClose={() => {}} />);

    const mark = await screen.findByText('Cited passage here.');
    expect(mark.tagName).toBe('MARK');
    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center' });
    });
    },
  );

  it('opens older PDF citations on their page and shows the cited text', async () => {
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'https://example.com/paper.pdf',
      title: 'Paper',
    });
    const citation: Citation = {
      source: 'Paper',
      document_id: 'document-1',
      page: 3,
      text: 'Evidence on page three.',
    };

    const { container } = render(
      <DocumentPreview document={document} citation={citation} onClose={() => {}} />,
    );

    expect(container.querySelector('iframe')?.getAttribute('src'))
      .toBe('https://example.com/paper.pdf#page=3');
    expect(screen.getByText('Evidence on page three.').tagName).toBe('MARK');
  });

  it('seeks YouTube previews to the cited timestamp', async () => {
    const document = await loadDocument({
      source_type: 'youtube',
      source_url: 'https://www.youtube.com/watch?v=video-123',
      title: 'Lecture',
    });

    const { container } = render(
      <DocumentPreview
        document={document}
        citation={{ source: 'Lecture', timestamp: 32.7 }}
        onClose={() => {}}
      />,
    );

    expect(container.querySelector('iframe')?.getAttribute('src'))
      .toBe('https://www.youtube.com/embed/video-123?start=32');
  });

  it('seeks an uploaded audio source to the cited timestamp', async () => {
    const document = await loadDocument({
      source_type: 'mp3' as Document['type'],
      source_url: 'uploads/document-1_lecture.mp3',
      title: 'Lecture',
    });
    const fetchFile = vi.spyOn(api, 'fetchDocumentFile').mockResolvedValue(
      new Blob(['audio'], { type: 'audio/mpeg' }),
    );
    vi.spyOn(api, 'fetchDocumentContent').mockResolvedValue('Transcript excerpt.');
    stubObjectUrls();

    const { container } = render(
      <DocumentPreview
        document={document}
        citation={{ source: 'Lecture', timestamp: 42 }}
        onClose={() => {}}
      />,
    );
    await waitFor(() => expect(container.querySelector('audio')).not.toBeNull());
    const player = container.querySelector('audio');
    expect(player).not.toBeNull();
    Object.defineProperty(player, 'currentTime', {
      configurable: true,
      writable: true,
      value: 0,
    });

    fireEvent.loadedMetadata(player!);

    await waitFor(() => expect(player?.currentTime).toBe(42));
    expect(fetchFile).toHaveBeenCalledWith('document-1');
  });

  it('keeps older text citations readable when passage offsets are missing', async () => {
    const document = await loadDocument({
      source_type: 'txt',
      source_url: 'uploads/document-1_notes.txt',
      title: 'Notes',
    });
    vi.spyOn(api, 'fetchDocumentContent').mockResolvedValue('Legacy source content');

    const { container } = render(
      <DocumentPreview
        document={document}
        citation={{ source: 'Notes', document_id: 'document-1', text: 'Older excerpt.' }}
        onClose={() => {}}
      />,
    );

    expect(await screen.findByText('Legacy source content')).toBeTruthy();
    expect(container.querySelector('mark')).toBeNull();
  });

  it('shows the guide and drafts a question scoped to its source', async () => {
    const document = await loadDocument({
      source_type: 'url',
      source_url: 'https://example.com/article',
      title: 'Example article',
    });
    const otherDocument = { ...document, id: 'document-2', name: 'Other article' };
    const guide = {
      summary: 'The source covers equipment. It also explains observations.',
      topics: ['Equipment', 'Observations', 'Image backups'],
    };
    const fetchGuide = vi.mocked(api.fetchDocumentGuide).mockResolvedValue(guide);
    vi.spyOn(api, 'fetchDocumentContent').mockResolvedValue('Article text');
    useStore.setState({
      currentProject: { id: 'project-1' } as Project,
      documents: [document, otherDocument],
    });
    const onClose = vi.fn();

    render(<DocumentPreview document={document} onClose={onClose} />);

    expect(await screen.findByText(guide.summary)).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: 'Equipment' }));

    expect(selectedSourceIds(useStore.getState())).toEqual(['document-1']);
    expect(useStore.getState().pendingMindMapQuestion).toEqual({
      projectId: 'project-1',
      question: 'What does this source say about Equipment?',
    });
    expect(fetchGuide).toHaveBeenCalledWith('document-1');
    expect(onClose).toHaveBeenCalledOnce();
  });
});
