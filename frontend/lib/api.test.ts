import { afterEach, describe, expect, it, vi } from 'vitest';

import api, { ApiError } from './api';


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
  it('fetches the runtime upload formats and file size limit', async () => {
    const config = { allowed_file_types: ['pdf', 'md'], max_file_size_mb: 23 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(config));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getUploadConfig()).resolves.toEqual(config);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/upload-config');
  });

  it('creates and reloads authenticated audio overview resources', async () => {
    const audio = {
      id: 'overview-1',
      status: 'queued',
      options: {
        document_ids: ['doc-1'],
        format: 'debate',
        length: 'short',
        focus: 'methods',
      },
      script: [],
      duration_seconds: null,
      error: null,
      created_at: '2026-10-25T00:00:00Z',
      updated_at: '2026-10-25T00:00:00Z',
      started_at: null,
      completed_at: null,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ enabled: true, items: [audio] }))
      .mockResolvedValueOnce(jsonResponse(audio, 202))
      .mockResolvedValueOnce(new Response('mp3 audio'))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.listAudioOverviews('project-1')).resolves.toEqual({
      enabled: true,
      items: [audio],
    });
    await api.createAudioOverview('project-1', {
      document_ids: ['doc-1'],
      format: 'debate',
      length: 'short',
      focus: 'methods',
    });
    await expect(api.fetchAudioOverviewFile('project-1', 'overview-1'))
      .resolves.toBeInstanceOf(Blob);
    await expect(api.deleteAudioOverview('project-1', 'overview-1'))
      .resolves.toBeUndefined();

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/api/projects/project-1/audio-overviews',
      '/api/projects/project-1/audio-overviews',
      '/api/projects/project-1/audio-overviews/overview-1/file',
      '/api/projects/project-1/audio-overviews/overview-1',
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(audio.options);
    expect(fetchMock.mock.calls[3][1].method).toBe('DELETE');
  });

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
        role: 'owner',
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
      role: 'owner',
    }]);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects');
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Accept')).toBe(
      'application/json',
    );
  });

  it('uses the project member endpoints and request bodies', async () => {
    const member = {
      user_id: 'user-1',
      username: 'reader',
      email: 'reader@example.com',
      role: 'viewer',
      created_at: '2026-01-01T00:00:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([member]))
      .mockResolvedValueOnce(jsonResponse(member))
      .mockResolvedValueOnce(jsonResponse({ ...member, role: 'editor' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getProjectMembers('project-1')).resolves.toEqual([member]);
    await api.addProjectMember('project-1', { email: member.email, role: 'viewer' });
    await api.updateProjectMember('project-1', 'user/1', { role: 'editor' });
    await api.removeProjectMember('project-1', 'user/1');

    expect(fetchMock.mock.calls.map(([path, init]) => [path, init.method])).toEqual([
      ['/api/projects/project-1/members', undefined],
      ['/api/projects/project-1/members', 'POST'],
      ['/api/projects/project-1/members/user%2F1', 'PATCH'],
      ['/api/projects/project-1/members/user%2F1', 'DELETE'],
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      email: member.email, role: 'viewer',
    });
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ role: 'editor' });
  });

  it('fetches analytics for the requested project and date range', async () => {
    const analytics = {
      days: 30,
      questions_by_day: [{ date: '2026-10-25', question_count: 2 }],
      conversation_count: 1,
      top_cited_sources: [],
      ratings: { up: 1, down: 0, unrated: 1 },
      recent_down_rated_questions: [],
      uncited_sources: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(analytics));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getProjectAnalytics('project-1', 30)).resolves.toEqual(analytics);

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/projects/project-1/analytics?days=30',
    );
  });

  it('normalizes backend document fields for components', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{
      id: 'document-1',
      title: 'Paper',
      source_type: 'pdf',
      source_url: null,
      is_owned_by_caller: true,
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
      isOwnedByCaller: true,
      content: undefined,
      meta: { author: 'Ada' },
      status: 'ready',
      error_message: undefined,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      chunk_count: 3,
    }]);
  });

  it('points an uploaded document at the API file route', async () => {
    // The backend stores a path on its own disk, which the browser cannot
    // fetch: it has to become a protected route on the frontend origin.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{
      id: 'document-1',
      title: 'Paper',
      source_type: 'pdf',
      source_url: 'uploads/document-1_paper.pdf',
      meta_json: {},
      status: 'ready',
      error_message: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      chunk_count: 1,
    }])));

    const [document] = await api.getDocuments('project-1');

    expect(document.url).toBe(
      '/api/docs/document-1/file',
    );
  });

  it.each([
    { type: 'url' as const, url: 'https://example.com/article' },
    { type: 'youtube' as const, url: 'https://youtu.be/abc123' },
  ])('leaves an external $type source URL untouched', async ({ type, url }) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{
      id: 'document-1',
      title: 'External source',
      source_type: type,
      source_url: url,
      meta_json: {},
      status: 'ready',
      error_message: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      chunk_count: 1,
    }])));

    const [document] = await api.getDocuments('project-1');

    expect(document.url).toBe(url);
  });

  it.each([
    {
      output: 'mind map',
      path: '/api/projects/project-1/mindmap',
      request: () => api.fetchProjectMindMap('project-1'),
    },
    {
      output: 'video summary',
      path: '/api/projects/project-1/video-summary',
      request: () => api.fetchProjectVideoSummary('project-1'),
    },
    {
      output: 'report',
      path: '/api/export/project/project-1/summary',
      request: () => api.exportProjectSummary('project-1'),
    },
    {
      output: 'audio summary',
      path: '/api/export/project/project-1/summary',
      request: () => api.fetchProjectSummaryText('project-1'),
    },
  ])('sends an explicit POST command for the $output', async ({ path, request }) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    await request();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(path);
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST',
    }));
  });

  it.each([
    { output: 'mind map', request: () => api.fetchProjectMindMap('project-1', ['doc-1']) },
    { output: 'video summary', request: () => api.fetchProjectVideoSummary('project-1', ['doc-1']) },
    { output: 'report', request: () => api.exportProjectSummary('project-1', ['doc-1']) },
    { output: 'audio summary', request: () => api.fetchProjectSummaryText('project-1', ['doc-1']) },
  ])('sends the source selection as JSON for the $output', async ({ request }) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    await request();

    const init = fetchMock.mock.calls[0][1];
    expect(JSON.parse(init.body)).toEqual({ document_ids: ['doc-1'] });
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
  });

  it('exports the current video summary scenes as a PowerPoint blob', async () => {
    const scenes = [{
      id: 'title',
      kind: 'title' as const,
      headline: 'Research',
      bullets: ['Finding'],
      narration: 'Narration.',
      document_id: null,
      source_label: 'Research source',
    }];
    const fetchMock = vi.fn().mockResolvedValue(new Response('pptx bytes', {
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const blob = await api.exportProjectVideoSummaryPptx('project-1', scenes);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/projects/project-1/video-summary/pptx',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          scenes: [{
            id: 'title',
            kind: 'title',
            headline: 'Research',
            bullets: ['Finding'],
            narration: 'Narration.',
            document_id: null,
          }],
        }),
      }),
    );
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Content-Type')).toBe(
      'application/json',
    );
    expect(blob.type).toBe(
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    );
    await expect(blob.text()).resolves.toBe('pptx bytes');
  });

  it('preserves the HTTP status on API errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: 'Video summary exceeds the export limits',
    }, 413)));
    const request = api.fetchProjectVideoSummary('project-1');

    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({ status: 413 });
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
      '/api/projects/project-1/upload',
    );
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }));
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/docs/document-1',
    );
  });

  it('lets the backend report unsupported file types', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      detail: 'File type is not supported. Allowed types: md, pdf, txt',
    }, 400));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['binary'], 'program.exe');

    await expect(api.uploadDocument('project-1', file)).rejects.toThrow(
      'File type is not supported. Allowed types: md, pdf, txt',
    );
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/project-1/upload');
  });

  it('uploads supported office files through the existing upload route', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        doc_id: 'document-1',
        status: 'queued',
        message: 'uploaded',
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'document-1',
        title: 'Report',
        source_type: 'docx',
        source_url: 'uploads/document-1_report.docx',
        meta_json: { file_extension: '.docx' },
        status: 'queued',
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        chunk_count: 0,
      }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.uploadDocument(
      'project-1',
      new File(['word'], 'report.docx'),
    );

    expect(result.type).toBe('docx');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/project-1/upload');
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
      `/api/projects/project-1/${endpoint}`,
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual(payload);
  });

  it('sends pasted text to the upload-text route', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ doc_id: 'document-1', status: 'queued', message: 'ok' }))
      .mockResolvedValueOnce(jsonResponse({
        id: 'document-1',
        title: 'Notes',
        source_type: 'text',
        meta_json: {},
        status: 'queued',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        chunk_count: 0,
      }));
    vi.stubGlobal('fetch', fetchMock);

    const document = await api.createDocument('project-1', {
      name: 'Notes',
      type: 'text',
      content: 'Pasted body',
    });

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/project-1/upload-text');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      title: 'Notes',
      text: 'Pasted body',
    });
    expect(document.type).toBe('text');
  });

  it('renames a document and rates a message', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        id: 'document-1',
        title: 'New name',
        source_type: 'pdf',
        meta_json: {},
        status: 'ready',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        chunk_count: 1,
      }))
      .mockResolvedValueOnce(jsonResponse({ id: 'message-1', rating: null }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.renameDocument('document-1', 'New name')).resolves.toEqual(
      expect.objectContaining({ id: 'document-1', name: 'New name' }),
    );
    await api.rateMessage('conversation-1', 'message-1', null);

    expect(fetchMock.mock.calls[0][0]).toBe('/api/docs/document-1');
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: 'PUT' }));
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/conversations/conversation-1/messages/message-1/rating',
    );
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ rating: null });
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
        citations: [{
          document_id: 'document-1',
          document_title: 'Research paper',
          page_num: 4,
          text_preview: 'Evidence',
        }],
        citation_checks: [{
          sentence_index: 0,
          cited_labels: [1],
          score: 0.31,
          supported: false,
        }],
      }],
    })));

    await expect(api.getMessages('conversation-1')).resolves.toEqual([{
      id: 'message-1',
      conversation_id: 'conversation-1',
      role: 'assistant',
      content: 'Answer',
      created_at: '2026-01-01T00:00:00Z',
      citations: [{
        source: 'Research paper',
        page: 4,
        text: 'Evidence',
        document_id: 'document-1',
        document_title: 'Research paper',
        page_num: 4,
        text_preview: 'Evidence',
      }],
      citation_checks: [{
        sentence_index: 0,
        cited_labels: [1],
        score: 0.31,
        supported: false,
      }],
    }]);
  });

  it('removes a document only from the selected project', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      status: 'success',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.deleteDocument('project-1', 'document-1');

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/projects/project-1/documents/document-1',
    );
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });

  it('does not expose process-wide cache clearing to browser callers', () => {
    expect('clearCache' in api).toBe(false);
  });

  it('normalizes a missing conversation title for string-only UI controls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{
      id: 'conversation-1',
      project_id: 'project-1',
      title: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      message_count: 0,
    }])));

    await expect(api.getConversations('project-1')).resolves.toEqual([{
      id: 'conversation-1',
      project_id: 'project-1',
      title: 'Untitled Conversation',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      message_count: 0,
    }]);
  });

  it('updates a conversation through the rename route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: 'conversation-1',
      project_id: 'project-1',
      title: 'Renamed chat',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      message_count: 2,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      api.updateConversation('conversation-1', 'Renamed chat'),
    ).resolves.toEqual(expect.objectContaining({
      id: 'conversation-1',
      title: 'Renamed chat',
      message_count: 2,
    }));
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/conversations/conversation-1',
    );
    expect(fetchMock.mock.calls[0][1].method).toBe('PUT');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      title: 'Renamed chat',
    });
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
    expect(fetchMock.mock.calls[0][0]).toBe('/api/query');
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

  it('reads FastAPI validation errors, which report detail as a list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: [
        { loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
      ],
    }, 422)));

    await expect(api.register({
      username: 'ada',
      email: 'ada@example.com',
      password: 'short',
    })).rejects.toThrow('String should have at least 8 characters');
  });

  it('signs in through the same-origin API route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      access_token: 'a-signed-token',
      token_type: 'bearer',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.login({ username: 'ada', password: 'lovelace-1843' }))
      .resolves.toEqual({ access_token: 'a-signed-token', token_type: 'bearer' });

    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/token');
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Content-Type')).toBe(
      'application/x-www-form-urlencoded',
    );
    expect((fetchMock.mock.calls[0][1].body as URLSearchParams).toString()).toBe(
      'username=ada&password=lovelace-1843',
    );
  });

  it('registers through the same-origin API route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: 'user-1',
      username: 'ada',
      email: 'ada@example.com',
      created_at: '2026-01-01T00:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.register({
      username: 'ada',
      email: 'ada@example.com',
      password: 'lovelace-1843',
    });

    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/register');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      username: 'ada',
      email: 'ada@example.com',
      password: 'lovelace-1843',
    });
  });

  it('reads the signed-in account with the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: 'user-1',
      username: 'ada',
      email: 'ada@example.com',
      created_at: '2026-01-01T00:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getAccount('a-signed-token')).resolves.toEqual(
      expect.objectContaining({ username: 'ada', email: 'ada@example.com' }),
    );
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/me');
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Authorization')).toBe(
      'Bearer a-signed-token',
    );
  });

  it('reports a failed sign-in through the detail message, not a status code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: 'Incorrect username or password',
    }, 401)));

    await expect(api.login({ username: 'ada', password: 'wrong' }))
      .rejects.toThrow('Incorrect username or password');
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
      '/api/export/conversation/conversation-1?format=markdown',
    );
  });

  it('detaches fetched export bytes before the browser download uses them', async () => {
    const arrayBuffer = vi.fn().mockResolvedValue(new TextEncoder().encode('# Export').buffer);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'text/markdown' }),
      arrayBuffer,
    }));

    const blob = await api.exportProject('project-1', 'markdown');

    expect(arrayBuffer).toHaveBeenCalledOnce();
    expect(blob.type).toBe('text/markdown');
    await expect(blob.text()).resolves.toBe('# Export');
  });

  it('keeps document-file previews backed by the response blob', async () => {
    const responseBlob = new Blob(['%PDF-preview'], { type: 'application/pdf' });
    const blob = vi.fn().mockResolvedValue(responseBlob);
    const arrayBuffer = vi.fn().mockRejectedValue(new Error('preview should not copy bytes'));
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/pdf' }),
      blob,
      arrayBuffer,
    });
    vi.stubGlobal('fetch', fetchMock);

    const file = await api.fetchDocumentFile('document-1');

    expect(file).toBe(responseBlob);
    expect(blob).toHaveBeenCalledOnce();
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/docs/document-1/file',
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it('fetches extracted document text with the session token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      content: '# Chapter One',
    }));
    vi.stubGlobal('fetch', fetchMock);

    const content = await api.fetchDocumentContent('document/1');

    expect(content).toBe('# Chapter One');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/docs/document%2F1/content',
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it('reports the demo account the sign-in page may offer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      enabled: true,
      username: 'demo',
      password: 'demo1234',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getDemoAccount()).resolves.toEqual({
      username: 'demo',
      password: 'demo1234',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/demo-account',
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it('reports no demo account when the deployment disabled it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      enabled: false,
      username: null,
      password: null,
    })));

    await expect(api.getDemoAccount()).resolves.toBeNull();
  });

  it('reports no demo account rather than failing the sign-in page', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('backend unreachable')));

    await expect(api.getDemoAccount()).resolves.toBeNull();
  });
});
