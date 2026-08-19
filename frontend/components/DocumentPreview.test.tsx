// @vitest-environment jsdom

import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import api, { type Document } from '@/lib/api';
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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(URL, 'createObjectURL');
  Reflect.deleteProperty(URL, 'revokeObjectURL');
});


describe('DocumentPreview', () => {
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

  it('leaves an external URL source pointing at the external site', async () => {
    const document = await loadDocument({
      source_type: 'url',
      source_url: 'https://example.com/article',
      title: 'Example article',
    });

    render(<DocumentPreview document={document} onClose={() => {}} />);

    expect(screen.getByTitle('Example article').getAttribute('src')).toBe(
      'https://example.com/article',
    );
  });
});
