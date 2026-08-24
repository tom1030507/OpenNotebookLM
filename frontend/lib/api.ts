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
}

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'error';
export type DocumentType = 'pdf' | 'url' | 'youtube' | 'text';

export interface Document {
  id: string;
  name: string;
  type: DocumentType;
  url?: string;
  content?: string;
  meta: Record<string, unknown>;
  status: DocumentStatus;
  error_message?: string;
  created_at: string;
  updated_at: string;
  chunk_count: number;
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

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  citations?: Citation[];
}

export interface QueryRequest {
  project_id: string;
  query: string;
  conversation_id?: string;
}

export interface QueryResponse {
  answer: string;
  sources: Record<string, unknown>[];
  chunks_used: number;
  model_used: string | null;
  usage: Record<string, unknown>;
  conversation_id: string | null;
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

interface ValidationErrorItem {
  msg?: string;
}

interface ErrorResponse {
  detail?: string | ValidationErrorItem[];
}

interface CacheClearResponse {
  /** -1 when the backend flushed a Redis database it cannot count. */
  cleared: number;
}


const configuredBaseUrl = (
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
).replace(/\/+$/, '');

/** Absolute base URL of the backend API, including the `/api` prefix. */
export const API_BASE_URL = configuredBaseUrl.endsWith('/api')
  ? configuredBaseUrl
  : `${configuredBaseUrl}/api`;

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
 * Resolve a backend path against the configured API base URL. Every caller
 * goes through this so a missing NEXT_PUBLIC_API_URL cannot produce a
 * relative `/undefined/...` request.
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
      return new Error(detail);
    }
  } catch {
    // Fall back to the HTTP status below when the response is not JSON.
  }

  return new Error(
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


const requestBlob = async (path: string): Promise<Blob> => {
  const headers = requestHeaders('*/*');
  const snapshot = snapshotSessionCredential(headers.get('Authorization'));
  const response = await fetch(apiUrl(path), {
    headers,
  });
  await guard(path, response, snapshot);

  // Chrome's download manager can retain a network-backed response Blob and
  // replay its protected URL without the bearer header. Copying the bytes makes
  // the later UI download depend only on browser-owned Blob data.
  const content = await response.arrayBuffer();
  return new Blob([content], { type: response.headers.get('Content-Type') || '' });
};


const requestText = async (path: string): Promise<string> => {
  const headers = requestHeaders('text/plain, text/markdown, */*');
  const snapshot = snapshotSessionCredential(headers.get('Authorization'));
  const response = await fetch(apiUrl(path), {
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

  return /^https?:\/\//i.test(document.source_url)
    ? document.source_url
    : documentFileUrl(document.id);
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

  /** Read the account a token belongs to. */
  getAccount(accessToken: string): Promise<Account> {
    return requestJson<Account>('/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  },

  async getProjects(): Promise<Project[]> {
    const response = await requestJson<ProjectListResponse>('/projects');
    return response.projects;
  },

  createProject(data: { name: string; description?: string }): Promise<Project> {
    return requestJson<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async deleteProject(projectId: string): Promise<void> {
    await requestJson(`/projects/${projectId}`, { method: 'DELETE' });
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

  async getDocuments(projectId: string, signal?: AbortSignal): Promise<Document[]> {
    const documents = await requestJson<BackendDocument[]>(
      `/projects/${projectId}/documents`,
      { signal },
    );
    return documents.map(normalizeDocument);
  },

  uploadDocument(projectId: string, file: File): Promise<Document> {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      return Promise.reject(new Error('Only PDF files are supported'));
    }

    const formData = new FormData();
    formData.append('file', file);
    return completeDocumentCreation(requestJson<FileUploadResponse>(
      `/projects/${projectId}/upload`,
      { method: 'POST', body: formData },
    ));
  },

  createDocument(projectId: string, data: CreateDocumentInput): Promise<Document> {
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

    return Promise.reject(new Error('Text sources are not supported by the API'));
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

  query(data: QueryRequest): Promise<QueryResponse> {
    return requestJson<QueryResponse>('/query', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  exportConversation(
    conversationId: string,
    format: ConversationExportFormat,
  ): Promise<Blob> {
    return requestBlob(
      `/export/conversation/${conversationId}?format=${encodeURIComponent(format)}`,
    );
  },

  exportProject(
    projectId: string,
    format: ProjectExportFormat,
  ): Promise<Blob> {
    return requestBlob(
      `/export/project/${projectId}?format=${encodeURIComponent(format)}`,
    );
  },

  fetchProjectMindMap(projectId: string): Promise<MindMap> {
    return requestJson<MindMap>(`/projects/${projectId}/mindmap`);
  },

  fetchProjectVideoSummary(projectId: string): Promise<VideoSummary> {
    return requestJson<VideoSummary>(`/projects/${projectId}/video-summary`);
  },

  exportProjectSummary(projectId: string): Promise<Blob> {
    return requestBlob(`/export/project/${projectId}/summary`);
  },

  /** The same summary as text, for reading aloud rather than downloading. */
  fetchProjectSummaryText(projectId: string): Promise<string> {
    return requestText(`/export/project/${projectId}/summary`);
  },

  /** Drop the server's cached query results and embeddings. */
  async clearCache(): Promise<number> {
    const response = await requestJson<CacheClearResponse>('/cache/clear', {
      method: 'DELETE',
    });
    return response.cleared;
  },
};


export default api;
