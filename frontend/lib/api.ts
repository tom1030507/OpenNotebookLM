import {
  readAccessToken,
  snapshotSessionCredential,
  type SessionCredentialSnapshot,
} from './session';
import { retireCurrentSession } from './sessionBoundary';


export interface Project {
  id: string;
  name: string;
  description: string | null;
  meta_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  document_count: number;
  conversation_count: number;
  role: ProjectRole;
  tags?: string[];
  cover_emoji?: string | null;
  cover_color?: string | null;
}

export interface ProjectSourceGroup {
  id: string;
  name: string;
  document_ids: string[];
}

export interface UploadConfig {
  allowed_file_types: string[];
  max_file_size_mb: number;
  max_text_characters: number;
  search_enabled: boolean;
}

export interface WebDiscoveryResult {
  title: string;
  url: string;
  snippet: string;
}

export type ProjectAnalyticsWindow = 7 | 30 | 90;

export interface ProjectAnalytics {
  days: ProjectAnalyticsWindow;
  questions_by_day: { date: string; question_count: number }[];
  conversation_count: number;
  top_cited_sources: { document_id: string; title: string; citation_count: number }[];
  ratings: { up: number; down: number; unrated: number };
  recent_down_rated_questions: { question: string; answered_at: string }[];
  uncited_sources: { document_id: string; title: string }[];
}

export interface ProjectSearchPassage {
  chunk_id: string;
  text: string;
  score: number;
  page_num: number | null;
  section: string | null;
}

export interface ProjectSearchDocument {
  document_id: string;
  title: string;
  source_type: string;
  passages: ProjectSearchPassage[];
}

export interface ProjectSearchProject {
  project_id: string;
  project_name: string;
  documents: ProjectSearchDocument[];
}

export interface ProjectSearchResponse {
  projects: ProjectSearchProject[];
}

export interface PersonalAPIKey {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export interface PersonalAPIKeyCreated extends PersonalAPIKey {
  api_key: string;
}

export type ProjectRole = 'owner' | 'editor' | 'viewer';

export interface ProjectMember {
  user_id: string;
  username: string;
  email: string;
  role: ProjectRole;
  created_at: string;
}

export type ChatRole = 'default' | 'learning_guide' | 'custom';
export type AnswerLength = 'default' | 'longer' | 'shorter';
export type OutputLanguage =
  | 'auto'
  | 'en'
  | 'zh-Hant'
  | 'zh-Hans'
  | 'ja'
  | 'ko'
  | 'es'
  | 'fr'
  | 'de';

export interface ChatSettings {
  role: ChatRole;
  instructions: string;
  answer_length: AnswerLength;
  output_language: OutputLanguage;
}

export type DocumentStatus = 'queued' | 'processing' | 'transcribing' | 'ready' | 'error';
export type DocumentType =
  | 'pdf'
  | 'docx'
  | 'pptx'
  | 'xlsx'
  | 'epub'
  | 'txt'
  | 'md'
  | 'mp3'
  | 'm4a'
  | 'wav'
  | 'ogg'
  | 'webm'
  | 'flac'
  | 'url'
  | 'youtube'
  | 'text';

export interface Document {
  id: string;
  name: string;
  type: DocumentType;
  url?: string;
  isOwnedByCaller: boolean;
  content?: string;
  meta: Record<string, unknown>;
  status: DocumentStatus;
  error_message?: string;
  created_at: string;
  updated_at: string;
  chunk_count: number;
  last_synced_at?: string | null;
  last_sync_changed?: boolean | null;
}

export interface WatchedFolderSettings {
  enabled: boolean;
  path: string | null;
}

export interface SourceGuide {
  summary: string;
  topics: string[];
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Citation extends Record<string, unknown> {
  source: string;
  page?: number;
  text?: string;
}

export type ReportFormat = 'briefing' | 'study_guide' | 'faq' | 'timeline' | 'custom';

export type StudioAudience = 'general' | 'beginner' | 'expert';
export type StudioOutputLength = 'short' | 'default' | 'long';

export interface StudioOutputOptions {
  focus?: string | null;
  audience?: StudioAudience;
  length?: StudioOutputLength;
}

export interface ProjectReportRequest extends StudioOutputOptions {
  format: ReportFormat;
  instruction?: string;
  document_ids?: string[];
}

export interface ProjectReport {
  markdown: string;
  citations: Citation[];
}

export interface ProjectTableRequest {
  instruction: string;
  columns?: string[];
  source_ids?: string[];
}

export interface ProjectTableCell {
  value: string;
  document_id: string | null;
  source_id: number | null;
}

export interface ProjectTableSource {
  id: number;
  document_id: string;
  title: string;
  excerpt: string;
}

export interface ProjectTable {
  columns: string[];
  rows: ProjectTableCell[][];
  sources: ProjectTableSource[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  citations?: Citation[];
  citation_checks?: CitationCheck[];
  rating?: MessageRating;
}

export interface CitationCheck {
  sentence_index: number;
  cited_labels: number[];
  score: number;
  supported: boolean;
}

export type StudioNoteKind = 'report' | 'mindmap' | 'video_summary';

export interface Note {
  id: string;
  project_id: string;
  title: string;
  /** Markdown. A saved answer carries its source list in here. */
  content: string;
  origin: 'manual' | 'answer' | 'studio';
  source_message_id: string | null;
  studio_kind: StudioNoteKind | null;
  payload_json: MindMap | VideoSummary | null;
  source_document_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface NoteSource {
  note_id: string;
  doc_id: string;
  status: string;
}

export interface NoteSourceBatch {
  sources: NoteSource[];
  failed_note_ids: string[];
}

export type MessageRating = 'up' | 'down' | null;

export interface QueryRequest {
  project_id: string;
  query: string;
  conversation_id?: string;
  /** Omitted to use every source in the project. */
  document_ids?: string[];
}

export interface QueryResponse {
  answer: string;
  sources: Record<string, unknown>[];
  chunks_used: number;
  model_used: string | null;
  usage: Record<string, unknown>;
  conversation_id: string | null;
  citation_checks?: CitationCheck[];
}

export interface StreamQueryResponse extends QueryResponse {
  message_id: string | null;
}

/** Generated once a project's sources are ready; empty without a model. */
export interface ProjectOverview {
  project_name: string;
  overview: string | null;
  questions: string[];
}

export type ConversationExportFormat = 'markdown' | 'json' | 'txt';
export type ProjectExportFormat = 'markdown' | 'json';

/** One node of a project's mind map. The shape is the same at every level. */
export interface MindMapNode {
  id: string;
  label: string;
  kind: 'project' | 'document' | 'topic';
  detail: string | null;
  document_id: string | null;
  children: MindMapNode[];
}

export interface MindMap {
  source_count?: number | null;
  total_source_count?: number | null;
  project_id: string;
  project_name: string;
  generated_at: string;
  /**
   * Which model named the topics, or `fallback` when the documents' own
   * structure did. The panel says which, rather than presenting an extracted
   * map as a generated one.
   */
  model_used: string;
  node_count: number;
  root: MindMapNode;
}

/** One scene of a project's video summary. The shape is the same for all kinds. */
export interface VideoScene {
  id: string;
  kind: 'title' | 'source' | 'closing';
  headline: string;
  bullets: string[];
  /** Read aloud over the slide. Never empty — the scene advances when it ends. */
  narration: string;
  document_id: string | null;
  /**
   * The source's own title, shown as the citation. Distinct from `headline`,
   * which may be a sentence a model wrote about it.
   */
  source_label: string | null;
}

export interface VideoSummary {
  project_id: string;
  project_name: string;
  generated_at: string;
  /**
   * Which model wrote the narration, or `fallback` when the documents' own
   * structure did. The player says which, rather than presenting an extracted
   * script as a written one.
   */
  model_used: string;
  scene_count: number;
  /**
   * How long the script takes to read out. The player computes its own timeline
   * rather than using this, because the progress bar has to agree with the scene
   * boundaries it is drawn from.
   */
  estimated_seconds: number;
  scenes: VideoScene[];
}

export interface StudyGenerationOptions {
  document_ids?: string[];
  count: number;
  focus?: string;
}

export interface StudySource {
  document_id: string;
  title: string;
  excerpt: string;
}

export interface Flashcard {
  front: string;
  back: string;
  document_id: string;
}

export interface QuizQuestion {
  question: string;
  options: [string, string, string, string];
  answer_index: number;
  explanation: string;
  document_id: string;
}

export interface StudyResponse<T> {
  project_id: string;
  project_name: string;
  generated_at: string;
  model_used: string;
  selected_ready_source_count: number;
  sources_considered: number;
  items: T[];
  sources: StudySource[];
}

export type FlashcardsResponse = StudyResponse<Flashcard>;
export type QuizResponse = StudyResponse<QuizQuestion>;

export type AudioOverviewFormat = 'deep_dive' | 'brief' | 'critique' | 'debate';
export type AudioOverviewLength = StudioOutputLength;

export interface AudioOverviewOptions extends StudioOutputOptions {
  document_ids?: string[];
  format: AudioOverviewFormat;
  length: AudioOverviewLength;
}

export interface AudioOverviewTurn {
  speaker: 'A' | 'B';
  text: string;
}

export interface AudioOverview {
  id: string;
  status: 'queued' | 'running' | 'ready' | 'failed';
  options: AudioOverviewOptions;
  script: AudioOverviewTurn[];
  duration_seconds: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AudioOverviewList {
  enabled: boolean;
  items: AudioOverview[];
}

interface ProjectListResponse {
  projects: Project[];
  total: number;
  page: number;
  per_page: number;
}

interface BackendDocument {
  id: string;
  title: string;
  source_type: DocumentType;
  source_url: string | null;
  content?: string | null;
  meta_json: Record<string, unknown> | null;
  status: DocumentStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  chunk_count: number;
  is_owned_by_caller: boolean;
  last_synced_at?: string | null;
  last_sync_changed?: boolean | null;
}

interface FileUploadResponse {
  doc_id: string;
  status: DocumentStatus;
  message: string;
}

interface BackendConversation {
  id: string;
  project_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
  messages?: BackendMessage[];
}

interface BackendCitation extends Record<string, unknown> {
  source?: string;
  title?: string;
  doc_id?: string;
  document_id?: string;
  document_title?: string;
  page?: number;
  page_num?: number;
  text?: string;
  text_snippet?: string;
  text_preview?: string;
}

interface BackendMessage {
  id: string;
  role: Message['role'];
  text: string;
  created_at: string;
  citations?: BackendCitation[] | null;
  citation_checks?: CitationCheck[] | null;
  rating?: MessageRating;
}

interface CreateDocumentInput {
  name: string;
  type: 'url' | 'youtube' | 'text';
  content?: string;
  url?: string;
}

export interface AccessToken {
  access_token: string;
  token_type: string;
}

export interface Account {
  id: string;
  username: string;
  email: string;
  created_at: string;
}

/** Credentials the sign-in page may present as ready to use. */
export interface DemoAccountHint {
  username: string;
  password: string;
}

interface DemoAccountResponse {
  enabled: boolean;
  username: string | null;
  password: string | null;
}

interface ValidationErrorItem {
  msg?: string;
}

interface ErrorResponse {
  detail?: string | ValidationErrorItem[];
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Same-origin prefix that Next proxies to the internal backend. */
export const API_BASE_URL = '/api';

/** The API route that streams the file stored for an uploaded document. */
export const documentFileUrl = (documentId: string): string =>
  `${API_BASE_URL}/docs/${encodeURIComponent(documentId)}/file`;

/**
 * True when a document's file lives behind the API's own protected route.
 *
 * Those bytes need the session token, and a browser cannot put an Authorization
 * header on an element's `src`, so they have to be fetched rather than linked.
 * An external source has no such problem.
 */
export const needsAuthorizedFetch = (document: Document): boolean =>
  document.url === documentFileUrl(document.id);


/**
 * Resolve a backend path against the same-origin API prefix. Next owns the
 * internal destination so browser bundles never contain Docker-only DNS.
 */
export const apiUrl = (path: string): string => `${API_BASE_URL}${path}`;


const describeDetail = (detail: ErrorResponse['detail']): string | null => {
  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    // FastAPI reports request validation failures as a list of field errors.
    const messages = detail
      .map((item) => item?.msg)
      .filter((message): message is string => Boolean(message));
    if (messages.length) {
      return messages.join('. ');
    }
  }

  return null;
};


const LOGIN_PATH = '/login';

/**
 * Requests whose 401 means "these credentials are wrong", not "your session is
 * over". Signing in reads the account it just minted a token for, and the form
 * shows what came back — a redirect from here would reload the page and throw
 * that message away.
 */
const CREDENTIAL_PATH_PREFIX = '/auth/';


/** The Authorization value for the stored session, or nothing when signed out. */
const authorization = (): string | null => {
  const token = readAccessToken();

  return token ? `Bearer ${token}` : null;
};


/**
 * Merge defaults, the stored credential, and caller overrides exactly as the
 * browser will dispatch them. The resulting Authorization is what the 401
 * guard snapshots, including an explicit override such as `getAccount` uses.
 */
const requestHeaders = (
  accept: string,
  init: RequestInit = {},
  includeJsonContentType = false,
): Headers => {
  const headers = new Headers({ Accept: accept });
  if (includeJsonContentType && init.body) {
    headers.set('Content-Type', 'application/json');
  }

  const storedAuthorization = authorization();
  if (storedAuthorization) {
    headers.set('Authorization', storedAuthorization);
  }

  if (init.headers) {
    new Headers(init.headers).forEach((value, key) => {
      headers.set(key, value);
    });
  }

  return headers;
};


/**
 * Give up a session the backend no longer accepts.
 *
 * Without this the workspace keeps a token every request will be refused for,
 * and each panel fails on its own on a screen with no way back to sign-in.
 */
const abandonSession = (snapshot: SessionCredentialSnapshot): void => {
  if (typeof window === 'undefined') {
    return;
  }

  if (!retireCurrentSession(snapshot)) {
    return;
  }

  if (window.location.pathname !== LOGIN_PATH) {
    window.location.assign(LOGIN_PATH);
  }
};


const extractError = async (response: Response): Promise<Error> => {
  try {
    const payload = await response.json() as ErrorResponse;
    const detail = describeDetail(payload.detail);
    if (detail) {
      return new ApiError(response.status, detail);
    }
  } catch {
    // Fall back to the HTTP status below when the response is not JSON.
  }

  return new ApiError(
    response.status,
    response.statusText || `Request failed with status ${response.status}`,
  );
};


/**
 * Let a successful response through, and turn any other into a thrown error.
 *
 * A refused token also ends the local session, so the workspace stops acting
 * signed in the moment the backend says otherwise.
 */
const guard = async (
  path: string,
  response: Response,
  snapshot: SessionCredentialSnapshot,
): Promise<void> => {
  if (response.ok) {
    return;
  }

  if (response.status === 401 && !path.startsWith(CREDENTIAL_PATH_PREFIX)) {
    abandonSession(snapshot);
  }

  throw await extractError(response);
};


/**
 * A Studio generation request, scoped to `documentIds` or reader options when
 * given. Without either, no body is sent and the request keeps its old shape.
 * The content type is explicit because the blob and text helpers do not set
 * one, and a bare string body would otherwise go out as text/plain.
 */
const studioRequest = (
  documentIds?: string[],
  options?: StudioOutputOptions,
): RequestInit => (
  documentIds || options
    ? {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(documentIds === undefined ? {} : { document_ids: documentIds }),
        ...options,
      }),
    }
    : { method: 'POST' }
);

const requestJson = async <T>(
  path: string,
  init: RequestInit = {},
): Promise<T> => {
  const isFormData = init.body instanceof FormData;
  const headers = requestHeaders('application/json', init, !isFormData);
  const snapshot = snapshotSessionCredential(headers.get('Authorization'));
  const response = await fetch(apiUrl(path), { ...init, headers });

  await guard(path, response, snapshot);

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
};


const fetchBlobResponse = async (
  path: string,
  init: RequestInit = {},
): Promise<Response> => {
  const headers = requestHeaders('*/*', init);
  const snapshot = snapshotSessionCredential(headers.get('Authorization'));
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
  });
  await guard(path, response, snapshot);
  return response;
};

const requestBlob = async (path: string): Promise<Blob> => {
  return (await fetchBlobResponse(path)).blob();
};

const requestDetachedExportBlob = async (
  path: string,
  init: RequestInit = {},
): Promise<Blob> => {
  const response = await fetchBlobResponse(path, init);

  // In reproducible Chromium/Playwright export flows, a response-backed Blob
  // can trigger a later protected URL request without the bearer header. Copy
  // export bytes before handing them to the browser download path.
  const content = await response.arrayBuffer();
  return new Blob([content], { type: response.headers.get('Content-Type') || '' });
};


const requestText = async (
  path: string,
  init: RequestInit = {},
): Promise<string> => {
  const headers = requestHeaders('text/plain, text/markdown, */*', init);
  const snapshot = snapshotSessionCredential(headers.get('Authorization'));
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
  });
  await guard(path, response, snapshot);

  return response.text();
};


/**
 * Turn a backend `source_url` into something a browser can load.
 *
 * A URL or YouTube source already carries an absolute external address. An
 * upload instead carries a path on the backend's own disk, which would resolve
 * against the frontend origin and 404 there, so it is served through the
 * document file route on the API instead.
 */
const resolveDocumentUrl = (document: BackendDocument): string | undefined => {
  if (!document.source_url) {
    return undefined;
  }

  if (/^https?:\/\//i.test(document.source_url)) {
    return document.source_url;
  }

  return document.source_type === 'pdf'
    ? documentFileUrl(document.id)
    : undefined;
};


const normalizeDocument = (document: BackendDocument): Document => {
  const metadataContent = typeof document.meta_json?.content === 'string'
    ? document.meta_json.content
    : undefined;

  return {
    id: document.id,
    name: document.title,
    type: document.source_type,
    url: resolveDocumentUrl(document),
    content: document.content || metadataContent,
    meta: document.meta_json || {},
    status: document.status,
    error_message: document.error_message || undefined,
    created_at: document.created_at,
    updated_at: document.updated_at,
    chunk_count: document.chunk_count,
    isOwnedByCaller: document.is_owned_by_caller,
    ...(document.last_synced_at !== undefined
      ? { last_synced_at: document.last_synced_at }
      : {}),
    ...(document.last_sync_changed !== undefined
      ? { last_sync_changed: document.last_sync_changed }
      : {}),
  };
};


const normalizeConversation = (
  conversation: BackendConversation,
): Conversation => ({
  id: conversation.id,
  project_id: conversation.project_id,
  title: conversation.title || 'Untitled Conversation',
  created_at: conversation.created_at,
  updated_at: conversation.updated_at,
  message_count: conversation.message_count ?? conversation.messages?.length ?? 0,
});


const normalizeCitation = (citation: BackendCitation): Citation => ({
  ...citation,
  source: citation.source
    || citation.document_title
    || citation.title
    || citation.document_id
    || citation.doc_id
    || 'Unknown source',
  ...(citation.page ?? citation.page_num) !== undefined
    ? { page: citation.page ?? citation.page_num }
    : {},
  ...(citation.text || citation.text_preview || citation.text_snippet)
    ? { text: citation.text || citation.text_preview || citation.text_snippet }
    : {},
});


const normalizeMessage = (
  conversationId: string,
  message: BackendMessage,
): Message => ({
  id: message.id,
  conversation_id: conversationId,
  role: message.role,
  content: message.text,
  created_at: message.created_at,
  ...(message.citations?.length
    ? { citations: message.citations.map(normalizeCitation) }
    : {}),
  ...(message.citation_checks?.length
    ? { citation_checks: message.citation_checks }
    : {}),
  ...(message.rating ? { rating: message.rating } : {}),
});


const getDocument = async (documentId: string): Promise<Document> => {
  const document = await requestJson<BackendDocument>(`/docs/${documentId}`);
  return normalizeDocument(document);
};


const completeDocumentCreation = async (
  response: Promise<FileUploadResponse>,
): Promise<Document> => {
  const accepted = await response;
  return getDocument(accepted.doc_id);
};


const api = {
  /** Exchange credentials for an access token. */
  login(credentials: { username: string; password: string }): Promise<AccessToken> {
    return requestJson<AccessToken>('/auth/token', {
      method: 'POST',
      // The token endpoint is an OAuth2 password form, not JSON.
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(credentials),
    });
  },

  /** Create an account. */
  register(account: {
    username: string;
    email: string;
    password: string;
  }): Promise<Account> {
    return requestJson<Account>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(account),
    });
  },

  /** Read the demo credentials this deployment publishes, if any. */
  async getDemoAccount(): Promise<DemoAccountHint | null> {
    try {
      const hint = await requestJson<DemoAccountResponse>('/auth/demo-account');
      if (!hint.enabled || !hint.username || !hint.password) {
        return null;
      }
      return { username: hint.username, password: hint.password };
    } catch {
      // A hint is a convenience. A backend that cannot answer must not be the
      // reason somebody with real credentials cannot reach the sign-in form.
      return null;
    }
  },

  /** Read the account a token belongs to. */
  getAccount(accessToken: string): Promise<Account> {
    return requestJson<Account>('/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  },

  createPersonalApiKey(name: string): Promise<PersonalAPIKeyCreated> {
    return requestJson<PersonalAPIKeyCreated>('/auth/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },

  listPersonalApiKeys(): Promise<PersonalAPIKey[]> {
    return requestJson<PersonalAPIKey[]>('/auth/api-keys');
  },

  revokePersonalApiKey(keyId: string): Promise<void> {
    return requestJson<void>('/auth/api-keys/' + encodeURIComponent(keyId), {
      method: 'DELETE',
    });
  },

  async getProjects(): Promise<Project[]> {
    const projects: Project[] = [];
    let page = 1;
    let total = 0;
    let perPage = 100;
    let pageSize = 0;
    do {
      const response = await requestJson<ProjectListResponse>(
        `/projects?page=${page}&per_page=100`,
      );
      projects.push(...response.projects);
      total = response.total;
      perPage = response.per_page;
      pageSize = response.projects.length;
      page += 1;
    } while (projects.length < total && pageSize > 0 && perPage > 0);
    return projects;
  },

  updateProjectTags(projectId: string, tags: string[]): Promise<string[]> {
    return requestJson<string[]>(`/projects/${projectId}/tags`, {
      method: 'PUT',
      body: JSON.stringify({ tags }),
    });
  },

  getProjectSourceGroups(projectId: string): Promise<ProjectSourceGroup[]> {
    return requestJson<ProjectSourceGroup[]>(`/projects/${projectId}/source-groups`);
  },

  createProjectSourceGroup(
    projectId: string,
    name: string,
  ): Promise<ProjectSourceGroup> {
    return requestJson<ProjectSourceGroup>(`/projects/${projectId}/source-groups`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },

  renameProjectSourceGroup(
    projectId: string,
    groupId: string,
    name: string,
  ): Promise<ProjectSourceGroup> {
    return requestJson<ProjectSourceGroup>(
      `/projects/${projectId}/source-groups/${groupId}`,
      { method: 'PATCH', body: JSON.stringify({ name }) },
    );
  },

  async deleteProjectSourceGroup(projectId: string, groupId: string): Promise<void> {
    await requestJson(
      `/projects/${projectId}/source-groups/${groupId}`,
      { method: 'DELETE' },
    );
  },

  setDocumentSourceGroup(
    projectId: string,
    documentId: string,
    groupId: string | null,
  ): Promise<ProjectSourceGroup[]> {
    return requestJson<ProjectSourceGroup[]>(
      `/projects/${projectId}/documents/${documentId}/group`,
      { method: 'PUT', body: JSON.stringify({ group_id: groupId }) },
    );
  },

  searchProjects(query: string): Promise<ProjectSearchResponse> {
    return requestJson<ProjectSearchResponse>('/search', {
      method: 'POST',
      body: JSON.stringify({ query }),
    });
  },

  getProjectMembers(projectId: string): Promise<ProjectMember[]> {
    return requestJson<ProjectMember[]>(`/projects/${projectId}/members`);
  },

  getProjectAnalytics(
    projectId: string,
    days: ProjectAnalyticsWindow = 7,
  ): Promise<ProjectAnalytics> {
    return requestJson<ProjectAnalytics>(
      `/projects/${projectId}/analytics?days=${days}`,
    );
  },

  addProjectMember(
    projectId: string,
    member: { username?: string; email?: string; role: 'viewer' | 'editor' },
  ): Promise<ProjectMember> {
    return requestJson<ProjectMember>(`/projects/${projectId}/members`, {
      method: 'POST',
      body: JSON.stringify(member),
    });
  },

  updateProjectMember(
    projectId: string,
    userId: string,
    member: { role: 'viewer' | 'editor' },
  ): Promise<ProjectMember> {
    return requestJson<ProjectMember>(
      `/projects/${projectId}/members/${encodeURIComponent(userId)}`,
      { method: 'PATCH', body: JSON.stringify(member) },
    );
  },

  async removeProjectMember(projectId: string, userId: string): Promise<void> {
    await requestJson(
      `/projects/${projectId}/members/${encodeURIComponent(userId)}`,
      { method: 'DELETE' },
    );
  },

  createProject(data: { name?: string; description?: string }): Promise<Project> {
    return requestJson<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateProject(
    projectId: string,
    data: { name?: string; description?: string; cover_emoji?: string | null; cover_color?: string | null },
  ): Promise<Project> {
    return requestJson<Project>(`/projects/${projectId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  duplicateProject(projectId: string): Promise<Project> {
    return requestJson<Project>(`/projects/${projectId}/duplicate`, { method: 'POST' });
  },

  async deleteProject(projectId: string): Promise<void> {
    await requestJson(`/projects/${projectId}`, { method: 'DELETE' });
  },

  getChatSettings(projectId: string): Promise<ChatSettings> {
    return requestJson<ChatSettings>(`/projects/${projectId}/chat-settings`);
  },

  updateChatSettings(projectId: string, settings: ChatSettings): Promise<ChatSettings> {
    return requestJson<ChatSettings>(`/projects/${projectId}/chat-settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  },

  /**
   * Download the file stored for an uploaded document.
   *
   * The route requires a token, so the bytes come through the client rather
   * than from an element's `src`. See `needsAuthorizedFetch`.
   */
  fetchDocumentFile(documentId: string): Promise<Blob> {
    return requestBlob(`/docs/${encodeURIComponent(documentId)}/file`);
  },

  /** Read extracted source text on demand for a document preview. */
  async fetchDocumentContent(documentId: string): Promise<string> {
    const response = await requestJson<{ content: string }>(
      `/docs/${encodeURIComponent(documentId)}/content`,
    );
    return response.content;
  },

  fetchDocumentGuide(documentId: string): Promise<SourceGuide> {
    return requestJson<SourceGuide>(`/docs/${encodeURIComponent(documentId)}/guide`);
  },

  async getDocuments(projectId: string, signal?: AbortSignal): Promise<Document[]> {
    const documents = await requestJson<BackendDocument[]>(
      `/projects/${projectId}/documents`,
      { signal },
    );
    return documents.map(normalizeDocument);
  },

  getWatchedFolder(projectId: string): Promise<WatchedFolderSettings> {
    return requestJson<WatchedFolderSettings>(
      `/projects/${projectId}/watched-folder`,
    );
  },

  setWatchedFolder(projectId: string, path: string | null): Promise<WatchedFolderSettings> {
    return requestJson<WatchedFolderSettings>(
      `/projects/${projectId}/watched-folder`,
      { method: 'PUT', body: JSON.stringify({ path }) },
    );
  },

  async resyncDocument(projectId: string, documentId: string): Promise<void> {
    await requestJson<FileUploadResponse>(
      `/projects/${projectId}/documents/${documentId}/resync`,
      { method: 'POST' },
    );
  },

  getUploadConfig(): Promise<UploadConfig> {
    return requestJson<UploadConfig>('/upload-config');
  },

  async discoverSources(
    projectId: string,
    query: string,
    count = 10,
  ): Promise<WebDiscoveryResult[]> {
    const response = await requestJson<{ results: WebDiscoveryResult[] }>(
      `/projects/${projectId}/discover`,
      { method: 'POST', body: JSON.stringify({ query, count }) },
    );
    return response.results;
  },

  uploadDocument(projectId: string, file: File): Promise<Document> {
    const formData = new FormData();
    formData.append('file', file);
    return completeDocumentCreation(requestJson<FileUploadResponse>(
      `/projects/${projectId}/upload`,
      { method: 'POST', body: formData },
    ));
  },

  createDocument(projectId: string, data: CreateDocumentInput): Promise<Document> {
    if (data.type === 'text') {
      return completeDocumentCreation(requestJson<FileUploadResponse>(
        `/projects/${projectId}/upload-text`,
        {
          method: 'POST',
          body: JSON.stringify({ title: data.name, text: data.content ?? '' }),
        },
      ));
    }

    if (!data.url) {
      return Promise.reject(new Error('A URL is required for this source type'));
    }

    if (data.type === 'url') {
      return completeDocumentCreation(requestJson<FileUploadResponse>(
        `/projects/${projectId}/upload-url`,
        {
          method: 'POST',
          body: JSON.stringify({ url: data.url, title: data.name }),
        },
      ));
    }

    if (data.type === 'youtube') {
      return completeDocumentCreation(requestJson<FileUploadResponse>(
        `/projects/${projectId}/upload-youtube`,
        {
          method: 'POST',
          body: JSON.stringify({ youtube_url: data.url, title: data.name }),
        },
      ));
    }

    return Promise.reject(new Error('Unsupported source type'));
  },

  async renameDocument(documentId: string, title: string): Promise<Document> {
    const document = await requestJson<BackendDocument>(`/docs/${documentId}`, {
      method: 'PUT',
      body: JSON.stringify({ title }),
    });
    return normalizeDocument(document);
  },

  async deleteDocument(projectId: string, documentId: string): Promise<void> {
    await requestJson(
      `/projects/${projectId}/documents/${documentId}`,
      { method: 'DELETE' },
    );
  },

  async getConversations(projectId: string): Promise<Conversation[]> {
    const conversations = await requestJson<BackendConversation[]>(
      `/projects/${projectId}/conversations`,
    );
    return conversations.map(normalizeConversation);
  },

  async createConversation(
    projectId: string,
    title?: string,
  ): Promise<Conversation> {
    const conversation = await requestJson<BackendConversation>(
      `/projects/${projectId}/conversations`,
      {
        method: 'POST',
        body: JSON.stringify({ title: title || null }),
      },
    );
    return normalizeConversation(conversation);
  },

  async updateConversation(
    conversationId: string,
    title: string,
  ): Promise<Conversation> {
    const conversation = await requestJson<BackendConversation>(
      `/conversations/${conversationId}`,
      {
        method: 'PUT',
        body: JSON.stringify({ title }),
      },
    );
    return normalizeConversation(conversation);
  },

  async deleteConversation(conversationId: string): Promise<void> {
    await requestJson(`/conversations/${conversationId}`, { method: 'DELETE' });
  },

  async getMessages(conversationId: string): Promise<Message[]> {
    const conversation = await requestJson<BackendConversation>(
      `/conversations/${conversationId}`,
    );
    return (conversation.messages || []).map(
      (message) => normalizeMessage(conversationId, message),
    );
  },

  async rateMessage(
    conversationId: string,
    messageId: string,
    rating: MessageRating,
  ): Promise<void> {
    await requestJson(
      `/conversations/${conversationId}/messages/${messageId}/rating`,
      { method: 'PUT', body: JSON.stringify({ rating }) },
    );
  },

  query(data: QueryRequest): Promise<QueryResponse> {
    return requestJson<QueryResponse>('/query', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async streamQuery(
    data: QueryRequest,
    signal?: AbortSignal,
    onToken?: (token: string) => void,
  ): Promise<StreamQueryResponse> {
    const init = { method: 'POST', body: JSON.stringify(data), signal };
    const headers = requestHeaders('text/event-stream', init, true);
    const snapshot = snapshotSessionCredential(headers.get('Authorization'));
    const response = await fetch(apiUrl('/query/stream'), { ...init, headers });
    await guard('/query/stream', response, snapshot);
    if (!response.body) throw new Error('Streaming query returned no response body.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result: StreamQueryResponse | null = null;
    const dispatch = (block: string) => {
      let event = 'message';
      const lines: string[] = [];
      for (const line of block.split(/\r\n|\r|\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
      }
      if (!lines.length) return;

      const payload = JSON.parse(lines.join('\n')) as Record<string, unknown>;
      if (event === 'token') {
        if (typeof payload.text !== 'string') throw new Error('Invalid streaming token.');
        onToken?.(payload.text);
      } else if (event === 'error') {
        throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Streaming query failed.');
      } else if (event === 'complete') {
        result = payload as unknown as StreamQueryResponse;
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        let boundary: RegExpExecArray | null;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          dispatch(buffer.slice(0, boundary.index));
          buffer = buffer.slice(boundary.index + boundary[0].length);
        }
        if (done) {
          if (buffer.trim()) dispatch(buffer);
          break;
        }
      }
    } catch (error) {
      await reader.cancel(error).catch(() => undefined);
      throw error;
    } finally {
      reader.releaseLock();
    }

    if (!result) throw new Error('Streaming query ended before completion.');
    return result;
  },

  exportConversation(
    conversationId: string,
    format: ConversationExportFormat,
  ): Promise<Blob> {
    return requestDetachedExportBlob(
      `/export/conversation/${conversationId}?format=${encodeURIComponent(format)}`,
    );
  },

  exportProject(
    projectId: string,
    format: ProjectExportFormat,
  ): Promise<Blob> {
    return requestDetachedExportBlob(
      `/export/project/${projectId}?format=${encodeURIComponent(format)}`,
    );
  },

  fetchProjectMindMap(
    projectId: string,
    documentIds?: string[],
    options?: StudioOutputOptions,
  ): Promise<MindMap> {
    return requestJson<MindMap>(
      `/projects/${projectId}/mindmap`,
      studioRequest(documentIds, options),
    );
  },

  fetchProjectVideoSummary(
    projectId: string,
    documentIds?: string[],
    options?: StudioOutputOptions,
  ): Promise<VideoSummary> {
    return requestJson<VideoSummary>(
      `/projects/${projectId}/video-summary`,
      studioRequest(documentIds, options),
    );
  },

  fetchProjectFlashcards(
    projectId: string,
    options: StudyGenerationOptions,
  ): Promise<FlashcardsResponse> {
    return requestJson<FlashcardsResponse>(`/projects/${projectId}/flashcards`, {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  fetchProjectQuiz(
    projectId: string,
    options: StudyGenerationOptions,
  ): Promise<QuizResponse> {
    return requestJson<QuizResponse>(`/projects/${projectId}/quiz`, {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  listAudioOverviews(projectId: string): Promise<AudioOverviewList> {
    return requestJson<AudioOverviewList>(`/projects/${projectId}/audio-overviews`);
  },

  createAudioOverview(
    projectId: string,
    options: AudioOverviewOptions & { document_ids?: string[] },
  ): Promise<AudioOverview> {
    return requestJson<AudioOverview>(`/projects/${projectId}/audio-overviews`, {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  getAudioOverview(projectId: string, overviewId: string): Promise<AudioOverview> {
    return requestJson<AudioOverview>(
      `/projects/${projectId}/audio-overviews/${overviewId}`,
    );
  },

  fetchAudioOverviewFile(projectId: string, overviewId: string): Promise<Blob> {
    return requestBlob(
      `/projects/${projectId}/audio-overviews/${overviewId}/file`,
    );
  },

  async deleteAudioOverview(projectId: string, overviewId: string): Promise<void> {
    await requestJson(
      `/projects/${projectId}/audio-overviews/${overviewId}`,
      { method: 'DELETE' },
    );
  },

  exportProjectVideoSummaryPptx(
    projectId: string,
    scenes: VideoScene[],
  ): Promise<Blob> {
    return requestDetachedExportBlob(
      `/projects/${projectId}/video-summary/pptx`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenes: scenes.map(({ id, kind, headline, bullets, narration, document_id }) => ({
            id, kind, headline, bullets, narration, document_id,
          })),
        }),
      },
    );
  },

  exportProjectSummary(projectId: string, documentIds?: string[]): Promise<Blob> {
    return requestDetachedExportBlob(
      `/export/project/${projectId}/summary`,
      studioRequest(documentIds),
    );
  },

  fetchProjectReport(projectId: string, options: ProjectReportRequest): Promise<ProjectReport> {
    return requestJson<ProjectReport>(`/projects/${projectId}/report`, {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  fetchProjectTable(projectId: string, options: ProjectTableRequest): Promise<ProjectTable> {
    return requestJson<ProjectTable>(`/projects/${projectId}/table`, {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  listNotes(projectId: string): Promise<Note[]> {
    return requestJson<Note[]>(`/projects/${projectId}/notes`);
  },

  /** With `source_message_id` the server writes the content from that answer. */
  createNote(
    projectId: string,
    note: {
      title: string;
      content?: string;
      source_message_id?: string;
      studio_kind?: StudioNoteKind;
      payload_json?: MindMap | VideoSummary;
    },
  ): Promise<Note> {
    return requestJson<Note>(`/projects/${projectId}/notes`, {
      method: 'POST',
      body: JSON.stringify(note),
    });
  },

  updateNote(
    projectId: string,
    noteId: string,
    changes: { title?: string; content?: string },
  ): Promise<Note> {
    return requestJson<Note>(`/projects/${projectId}/notes/${noteId}`, {
      method: 'PUT',
      body: JSON.stringify(changes),
    });
  },

  fetchProjectOverview(projectId: string): Promise<ProjectOverview> {
    return requestJson<ProjectOverview>(`/projects/${projectId}/overview`);
  },

  async fetchFollowUpQuestions(conversationId: string): Promise<string[]> {
    const response = await requestJson<{ questions: string[] }>(
      `/conversations/${conversationId}/follow-ups`,
      { method: 'POST' },
    );
    return response.questions;
  },

  async deleteNote(projectId: string, noteId: string): Promise<void> {
    await requestJson(`/projects/${projectId}/notes/${noteId}`, { method: 'DELETE' });
  },

  convertNoteToSource(projectId: string, noteId: string): Promise<NoteSource> {
    return requestJson<NoteSource>(`/projects/${projectId}/notes/${noteId}/source`, {
      method: 'POST',
    });
  },

  convertAllNotesToSources(projectId: string): Promise<NoteSourceBatch> {
    return requestJson<NoteSourceBatch>(`/projects/${projectId}/notes/sources`, {
      method: 'POST',
    });
  },

  /** The same summary as text, for reading aloud rather than downloading. */
  fetchProjectSummaryText(
    projectId: string,
    documentIds?: string[],
    options?: StudioOutputOptions,
  ): Promise<string> {
    return requestText(
      `/export/project/${projectId}/summary`,
      studioRequest(documentIds, options),
    );
  },

};


export default api;
