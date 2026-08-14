// @vitest-environment jsdom

import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
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


afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe('DocumentPreview', () => {
  it('loads an uploaded PDF from the API origin, not the app origin', async () => {
    const document = await loadDocument({
      source_type: 'pdf',
      source_url: 'uploads/document-1_paper.pdf',
      title: 'Paper',
    });

    render(<DocumentPreview document={document} onClose={() => {}} />);

    // A backend-relative path resolves against localhost:3000 and 404s there,
    // which is exactly the empty preview pane this pins shut.
    expect(screen.getByTitle('Paper').getAttribute('src')).toBe(
      'http://localhost:8000/api/docs/document-1/file',
    );
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
