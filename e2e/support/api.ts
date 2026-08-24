import { expect, type APIRequestContext, type APIResponse } from '@playwright/test';

import type { Account } from './ui.js';
import { runtime } from './runtime.js';

export interface Project {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  conversation_count: number;
}

export interface DocumentRecord {
  id: string;
  title: string;
  source_type: 'pdf' | 'url' | 'youtube';
  source_url: string | null;
  status: 'queued' | 'processing' | 'ready' | 'error';
  error_message: string | null;
  chunk_count: number;
}

export interface DocumentStatus {
  id: string;
  status: 'queued' | 'processing' | 'ready' | 'error';
  error_message: string | null;
  progress: number | null;
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  project_id: string;
  title: string;
  messages: Array<{
    id: string;
    role: 'user' | 'assistant';
    text: string;
    citations: Array<{
      document_id: string;
      document_title: string;
      chunk_id: string;
      text_preview: string;
    }>;
  }>;
}

export interface QueryResult {
  answer: string;
  sources: Array<{
    id: number;
    document_id: string;
    document_title: string;
    chunk_id: string;
    text_preview: string;
    score: number;
  }>;
  chunks_used: number;
  model_used: string | null;
  conversation_id: string;
}

export class E2EApi {
  private token: string | undefined;

  constructor(private readonly request: APIRequestContext) {}

  private authorization(): Record<string, string> {
    if (!this.token) {
      throw new Error('E2EApi.login must be called before an authenticated request');
    }
    return { Authorization: `Bearer ${this.token}` };
  }

  private async json<T>(response: APIResponse): Promise<T> {
    if (!response.ok()) {
      throw new Error(`${response.url()} returned ${response.status()}: ${await response.text()}`);
    }
    return response.json() as Promise<T>;
  }

  async register(account: Account): Promise<void> {
    await this.json(await this.request.post(`${runtime.apiUrl}/auth/register`, {
      data: account,
    }));
  }

  async login(account: Pick<Account, 'username' | 'password'>): Promise<string> {
    const result = await this.json<{ access_token: string }>(
      await this.request.post(`${runtime.apiUrl}/auth/token`, { form: account }),
    );
    this.token = result.access_token;
    return result.access_token;
  }

  async createProject(name: string, description = ''): Promise<Project> {
    return this.json(await this.request.post(`${runtime.apiUrl}/projects`, {
      headers: this.authorization(),
      data: { name, description },
    }));
  }

  async listProjects(): Promise<Project[]> {
    const result = await this.json<{ projects: Project[] }>(
      await this.request.get(`${runtime.apiUrl}/projects`, { headers: this.authorization() }),
    );
    return result.projects;
  }

  async projectDocumentsResponse(projectId: string): Promise<APIResponse> {
    return this.request.get(`${runtime.apiUrl}/projects/${projectId}/documents`, {
      headers: this.authorization(),
    });
  }

  async listProjectDocuments(projectId: string): Promise<DocumentRecord[]> {
    return this.json(await this.projectDocumentsResponse(projectId));
  }

  async uploadUrl(projectId: string, url: string): Promise<string> {
    const result = await this.json<{ doc_id: string }>(
      await this.request.post(`${runtime.apiUrl}/projects/${projectId}/upload-url`, {
        headers: this.authorization(),
        data: { url, title: url },
      }),
    );
    return result.doc_id;
  }

  async documentStatus(documentId: string): Promise<DocumentStatus> {
    return this.json(await this.request.get(`${runtime.apiUrl}/docs/${documentId}/status`, {
      headers: this.authorization(),
    }));
  }

  async waitForDocumentReady(documentId: string, timeout = 30_000): Promise<DocumentStatus> {
    let latest: DocumentStatus | undefined;
    await expect.poll(async () => {
      latest = await this.documentStatus(documentId);
      if (latest.status === 'error') {
        throw new Error(`Document ${documentId} failed: ${latest.error_message ?? 'unknown error'}`);
      }
      return latest.status;
    }, { timeout, intervals: [250, 500, 1_000] }).toBe('ready');
    return latest as DocumentStatus;
  }

  async createConversation(projectId: string, title: string): Promise<Conversation> {
    return this.json(await this.request.post(`${runtime.apiUrl}/projects/${projectId}/conversations`, {
      headers: this.authorization(),
      data: { title },
    }));
  }

  async listConversations(projectId: string): Promise<Conversation[]> {
    return this.json(await this.request.get(`${runtime.apiUrl}/projects/${projectId}/conversations`, {
      headers: this.authorization(),
    }));
  }

  async conversation(conversationId: string): Promise<ConversationDetail> {
    return this.json(await this.request.get(`${runtime.apiUrl}/conversations/${conversationId}`, {
      headers: this.authorization(),
    }));
  }

  async query(projectId: string, conversationId: string, query: string): Promise<QueryResult> {
    return this.json(await this.request.post(`${runtime.apiUrl}/query`, {
      headers: this.authorization(),
      data: { project_id: projectId, conversation_id: conversationId, query },
    }));
  }
}
