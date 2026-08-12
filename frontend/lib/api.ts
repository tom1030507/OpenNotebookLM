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

interface ErrorResponse {
  detail?: string;
}


const configuredBaseUrl = (
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
).replace(/\/+$/, '');
const API_BASE_URL = configuredBaseUrl.endsWith('/api')
  ? configuredBaseUrl
  : `${configuredBaseUrl}/api`;


const extractError = async (response: Response): Promise<Error> => {
  try {
    const payload = await response.json() as ErrorResponse;
    if (payload.detail) {
      return new Error(payload.detail);
    }
  } catch {
    // Fall back to the HTTP status below when the response is not JSON.
  }

  return new Error(
    response.statusText || `Request failed with status ${response.status}`,
  );
};


const requestJson = async <T>(
  path: string,
  init: RequestInit = {},
): Promise<T> => {
  const isFormData = init.body instanceof FormData;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(!isFormData && init.body ? { 'Content-Type': 'application/json' } : {}),
    ...(init.headers as Record<string, string> | undefined),
  };
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    throw await extractError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
};


const requestBlob = async (path: string): Promise<Blob> => {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: '*/*' },
  });
  if (!response.ok) {
    throw await extractError(response);
  }
  return response.blob();
};


const normalizeDocument = (document: BackendDocument): Document => {
  const metadataContent = typeof document.meta_json?.content === 'string'
    ? document.meta_json.content
    : undefined;

  return {
    id: document.id,
    name: document.title,
    type: document.source_type,
    url: document.source_url || undefined,
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

  async getDocuments(projectId: string): Promise<Document[]> {
    const documents = await requestJson<BackendDocument[]>(
      `/projects/${projectId}/documents`,
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
};


export default api;
