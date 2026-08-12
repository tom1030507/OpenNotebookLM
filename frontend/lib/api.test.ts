import { afterEach, describe, expect, it, vi } from 'vitest';

import api from './api';


const jsonResponse = (body: unknown, status = 200) => new Response(
  JSON.stringify(body),
  {
    status,
    headers: { 'Content-Type': 'application/json' },
  },
);


afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe('API client', () => {
  it('unwraps the paginated project response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      projects: [{
        id: 'project-1',
        name: 'Research',
        description: null,
        meta_json: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        document_count: 0,
        conversation_count: 0,
      }],
      total: 1,
      page: 1,
      per_page: 10,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getProjects()).resolves.toEqual([{
      id: 'project-1',
      name: 'Research',
      description: null,
      meta_json: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      document_count: 0,
      conversation_count: 0,
    }]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/projects',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
  });

  it('normalizes backend document fields for components', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{
      id: 'document-1',
      title: 'Paper',
      source_type: 'pdf',
      source_url: null,
      meta_json: { author: 'Ada' },
      status: 'ready',
      error_message: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      chunk_count: 3,
    }])));

    await expect(api.getDocuments('project-1')).resolves.toEqual([{
      id: 'document-1',
      name: 'Paper',
      type: 'pdf',
      url: undefined,
      content: undefined,
      meta: { author: 'Ada' },
      status: 'ready',
      error_message: undefined,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      chunk_count: 3,
    }]);
  });

  it('fetches the complete document after a file upload', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        doc_id: 'document-1',
        status: 'queued',
        message: 'uploaded',
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'document-1',
        title: 'Paper',
        source_type: 'pdf',
        source_url: null,
        meta_json: {},
        status: 'queued',
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        chunk_count: 0,
      }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['pdf'], 'paper.pdf', { type: 'application/pdf' });

    const result = await api.uploadDocument('project-1', file);

    expect(result).toEqual(expect.objectContaining({
      id: 'document-1',
      name: 'Paper',
      type: 'pdf',
    }));
    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://localhost:8000/api/projects/project-1/upload',
    );
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }));
    expect(fetchMock.mock.calls[1][0]).toBe(
      'http://localhost:8000/api/docs/document-1',
    );
  });

  it.each([
    {
      type: 'url' as const,
      endpoint: 'upload-url',
      payload: { url: 'https://example.com', title: 'Example' },
    },
    {
      type: 'youtube' as const,
      endpoint: 'upload-youtube',
      payload: { youtube_url: 'https://youtu.be/video', title: 'Video' },
    },
  ])('uses the $endpoint route for a $type document', async ({ type, endpoint, payload }) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        doc_id: 'document-1',
        status: 'queued',
        message: 'accepted',
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'document-1',
        title: payload.title,
        source_type: type,
        source_url: type === 'url' ? payload.url : payload.youtube_url,
        meta_json: {},
        status: 'queued',
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        chunk_count: 0,
      }));
    vi.stubGlobal('fetch', fetchMock);

    await api.createDocument('project-1', {
      name: payload.title,
      type,
      url: type === 'url' ? payload.url : payload.youtube_url,
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://localhost:8000/api/projects/project-1/${endpoint}`,
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual(payload);
  });

  it('normalizes conversation messages and citations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      id: 'conversation-1',
      project_id: 'project-1',
      title: 'First chat',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      messages: [{
        id: 'message-1',
        role: 'assistant',
        text: 'Answer',
        created_at: '2026-01-01T00:00:00Z',
        citations: [{ doc_id: 'document-1', page_num: 4, text_snippet: 'Evidence' }],
      }],
    })));

    await expect(api.getMessages('conversation-1')).resolves.toEqual([{
      id: 'message-1',
      conversation_id: 'conversation-1',
      role: 'assistant',
      content: 'Answer',
      created_at: '2026-01-01T00:00:00Z',
      citations: [{
        source: 'document-1',
        page: 4,
        text: 'Evidence',
        doc_id: 'document-1',
        page_num: 4,
        text_snippet: 'Evidence',
      }],
    }]);
  });

  it('sends a non-streaming query to the active backend route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: 'conversation-1',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.query({
      project_id: 'project-1',
      query: 'Question',
      conversation_id: 'conversation-1',
    })).resolves.toEqual(expect.objectContaining({ answer: 'Answer' }));
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/query');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      project_id: 'project-1',
      query: 'Question',
      conversation_id: 'conversation-1',
    });
  });

  it('surfaces FastAPI detail messages for failed requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: 'Project not found',
    }, 404)));

    await expect(api.getDocuments('missing')).rejects.toThrow('Project not found');
  });

  it('returns export responses as blobs', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('# Conversation', {
      status: 200,
      headers: { 'Content-Type': 'text/markdown' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const blob = await api.exportConversation('conversation-1', 'markdown');

    expect(await blob.text()).toBe('# Conversation');
    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://localhost:8000/api/export/conversation/conversation-1?format=markdown',
    );
  });
});
