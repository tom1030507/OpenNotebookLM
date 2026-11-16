/**
 * Bundled, read-only preview data. This adapter handles only the offline
 * session marker: real account requests always keep using the backend.
 */
import type { Project, Note, ChatSettings, SourceGuide, ProjectOverview, AudioOverviewList } from './api';

export const OFFLINE_DEMO_CREDENTIALS = { username: 'demo', password: 'demo1234' } as const;
export const OFFLINE_DEMO_BACKEND_REQUIRED = 'This action needs a running backend. Exit the offline demo and sign in to your server.';
const createdAt = '2026-11-16T00:00:00Z';
const projectId = 'offline-demo-project';
const documentId = 'offline-demo-source';
const conversationId = 'offline-demo-conversation';
const sourceText = 'Citations connect an answer to the source material behind it. Open a citation, read the passage in context, and check whether it supports the claim. Keep useful findings in notes so you can revisit both the answer and its evidence.';

const project: Project = {
  id: projectId,
  name: 'Research demo',
  description: 'Sample sources, answers, and notes for exploring the workspace',
  meta_json: {},
  created_at: createdAt,
  updated_at: createdAt,
  document_count: 1,
  conversation_count: 1,
  role: 'owner',
};

const document = {
  id: documentId,
  title: 'A guide to checking your sources',
  source_type: 'text',
  source_url: null,
  content: sourceText,
  meta_json: {},
  status: 'ready',
  error_message: null,
  is_owned_by_caller: true,
  created_at: createdAt,
  updated_at: createdAt,
  chunk_count: 1,
};

const conversation = {
  id: conversationId,
  project_id: projectId,
  title: 'How do citations help me check an answer?',
  created_at: createdAt,
  updated_at: createdAt,
  message_count: 2,
  messages: [{
    id: 'offline-demo-question',
    role: 'user',
    text: 'How do citations help me check an answer?',
    created_at: createdAt,
  }, {
    id: 'offline-demo-answer',
    role: 'assistant',
    text: 'Citations connect a claim to its supporting passage. Open the numbered reference to read the source, then check whether the passage supports what the answer says. [1]\n\n### A useful reading habit\n\n- Read the cited passage in context\n- Compare the claim with what the source actually says\n- Save useful findings alongside their evidence\n\nThis is a sample answer included with the offline demo. New answers need a running backend.',
    created_at: createdAt,
    citations: [{ id: 1, source: document.title, document_id: documentId, text: sourceText }],
  }],
};

const notes: Note[] = [{
  id: 'offline-demo-note',
  project_id: projectId,
  title: 'A reading checklist',
  content: '## Check the evidence\n\n1. Open a numbered citation\n2. Read the supporting passage\n3. Compare it with the answer\n\nThis sample note is read-only. Connect a backend to save your own research.',
  origin: 'manual',
  source_message_id: null,
  studio_kind: null,
  payload_json: null,
  created_at: createdAt,
  updated_at: createdAt,
}];

const routes = new Map<string, unknown>([
  ['/projects', { projects: [project], total: 1, page: 1, per_page: 100 }],
  [`/projects/${projectId}/documents`, [document]],
  [`/projects/${projectId}/conversations`, [conversation]],
  [`/projects/${projectId}/notes`, notes],
  [`/projects/${projectId}/source-groups`, []],
  [`/projects/${projectId}/git-repositories`, { repositories: [] }],
  [`/projects/${projectId}/watched-folder`, { enabled: false, path: null }],
  [`/projects/${projectId}/members`, []],
  [`/projects/${projectId}/overview`, {
    project_name: project.name,
    overview: 'Explore a sample source, open the saved conversation to inspect its citation, and read the note in Studio. Everything in this workspace is bundled with the frontend.',
    questions: [],
  } satisfies ProjectOverview],
  [`/projects/${projectId}/chat-settings`, {
    role: 'default', instructions: '', answer_length: 'default', output_language: 'auto', model: null,
  } satisfies ChatSettings],
  [`/projects/${projectId}/audio-overviews`, { enabled: true, voices: [], items: [] } satisfies AudioOverviewList],
  [`/conversations/${conversationId}`, conversation],
  [`/conversations/${conversationId}/follow-ups`, { questions: [] }],
  [`/docs/${documentId}`, document],
  [`/docs/${documentId}/content`, { content: sourceText }],
  [`/docs/${documentId}/guide`, {
    summary: 'A sample source about checking answers against their citations.',
    topics: ['Citations', 'Evidence', 'Reading notes'],
  } satisfies SourceGuide],
  ['/models', []],
  ['/auth/demo-account', { enabled: false, username: null, password: null }],
  ['/auth/me', { id: 'offline-demo-user', username: 'demo', email: 'demo@example.com', created_at: createdAt }],
  ['/upload-config', {
    allowed_file_types: ['pdf', 'txt', 'md'], max_file_size_mb: 50,
    max_text_characters: 100000, search_enabled: false,
  }],
]);

/** Resolve allowlisted reads; reject every mutation and generation locally. */
export function getOfflineDemoResponse(path: string, init: RequestInit = {}): Response {
  const pathname = path.split('?')[0];
  if ((init.method ?? 'GET').toUpperCase() !== 'GET') {
    return Response.json({ detail: OFFLINE_DEMO_BACKEND_REQUIRED }, { status: 503 });
  }
  if (routes.has(pathname)) return Response.json(routes.get(pathname));
  if (pathname.startsWith('/export/') || pathname.endsWith('/file')) {
    return Response.json({ detail: OFFLINE_DEMO_BACKEND_REQUIRED }, { status: 503 });
  }
  return Response.json({ detail: 'This item is not part of the offline demo.' }, { status: 404 });
}
