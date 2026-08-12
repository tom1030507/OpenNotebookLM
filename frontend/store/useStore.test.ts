import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Conversation, Document, Message, Project } from '@/lib/api';


const testStorage = vi.hoisted(() => {
  const values = new Map<string, string>();
  const storage = {
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
    get length() {
      return values.size;
    },
  };
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
  });
  return storage;
});


const apiMock = vi.hoisted(() => ({
  getProjects: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  getDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  createDocument: vi.fn(),
  deleteDocument: vi.fn(),
  getConversations: vi.fn(),
  createConversation: vi.fn(),
  updateConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getMessages: vi.fn(),
  query: vi.fn(),
}));


vi.mock('@/lib/api', () => ({ default: apiMock }));


import useStore from './useStore';


const project = (id: string): Project => ({
  id,
  name: `Project ${id}`,
  description: null,
  meta_json: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
});

const conversation = (id: string, projectId: string): Conversation => ({
  id,
  project_id: projectId,
  title: 'First chat',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  message_count: 0,
});

const authoritativeMessage: Message = {
  id: 'message-1',
  conversation_id: 'conversation-1',
  role: 'assistant',
  content: 'Answer',
  created_at: '2026-01-01T00:00:00Z',
};

const readyDocument: Document = {
  id: 'document-1',
  name: 'Paper',
  type: 'pdf',
  meta: {},
  status: 'ready',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  chunk_count: 1,
};


const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
};


const setEmptyState = () => {
  useStore.setState({
    projects: [],
    currentProject: null,
    loadingProjects: false,
    documents: [],
    loadingDocuments: false,
    uploadProgress: {},
    conversations: [],
    currentConversation: null,
    messages: [],
    loadingConversations: false,
    loadingMessages: false,
    sidebarOpen: true,
    studioOpen: true,
  });
};


beforeEach(() => {
  vi.clearAllMocks();
  testStorage.clear();
  setEmptyState();
  apiMock.getDocuments.mockResolvedValue([]);
  apiMock.getConversations.mockResolvedValue([]);
});


describe('application store', () => {
  it('resets to an empty project state instead of a fake backend id', () => {
    useStore.getState().reset();

    expect(useStore.getState().projects).toEqual([]);
    expect(useStore.getState().currentProject).toBeNull();
  });

  it('selects and loads the first real project after fetching', async () => {
    apiMock.getProjects.mockResolvedValue([project('project-1')]);

    await useStore.getState().fetchProjects();

    expect(useStore.getState().currentProject?.id).toBe('project-1');
    expect(apiMock.getDocuments).toHaveBeenCalledWith('project-1');
    expect(apiMock.getConversations).toHaveBeenCalledWith('project-1');
  });

  it('preserves a selected project that still exists after refresh', async () => {
    useStore.setState({ currentProject: project('project-2') });
    apiMock.getProjects.mockResolvedValue([
      project('project-1'),
      project('project-2'),
    ]);

    await useStore.getState().fetchProjects();

    expect(useStore.getState().currentProject?.id).toBe('project-2');
    expect(apiMock.getDocuments).toHaveBeenCalledWith('project-2');
    expect(apiMock.getConversations).toHaveBeenCalledWith('project-2');
  });

  it('clears stale scoped state when a refresh selects a different project', async () => {
    useStore.setState({
      currentProject: project('removed-project'),
      documents: [readyDocument],
      conversations: [conversation('conversation-1', 'removed-project')],
      currentConversation: conversation('conversation-1', 'removed-project'),
      messages: [authoritativeMessage],
    });
    apiMock.getProjects.mockResolvedValue([project('project-1')]);

    await useStore.getState().fetchProjects();

    expect(useStore.getState()).toEqual(expect.objectContaining({
      currentProject: project('project-1'),
      currentConversation: null,
      messages: [],
    }));
  });

  it('clears project-scoped state before loading a different project', () => {
    useStore.setState({
      currentProject: project('project-1'),
      documents: [readyDocument],
      conversations: [conversation('conversation-1', 'project-1')],
      currentConversation: conversation('conversation-1', 'project-1'),
      messages: [authoritativeMessage],
    });

    useStore.getState().selectProject(project('project-2'));

    expect(useStore.getState()).toEqual(expect.objectContaining({
      currentProject: project('project-2'),
      documents: [],
      conversations: [],
      currentConversation: null,
      messages: [],
    }));
  });

  it('ignores a document response for a project that is no longer selected', async () => {
    useStore.setState({ currentProject: project('project-2') });
    apiMock.getDocuments.mockResolvedValue([readyDocument]);

    await useStore.getState().fetchDocuments('project-1');

    expect(useStore.getState().documents).toEqual([]);
  });

  it('ignores a completed upload after switching projects', async () => {
    const upload = deferred<Document>();
    useStore.setState({ currentProject: project('project-1') });
    apiMock.uploadDocument.mockReturnValue(upload.promise);

    const pendingUpload = useStore.getState().uploadDocument(
      'project-1',
      new File(['pdf'], 'paper.pdf'),
    );
    useStore.getState().selectProject(project('project-2'));
    upload.resolve(readyDocument);
    await pendingUpload;

    expect(useStore.getState().documents).toEqual([]);
  });

  it('ignores a created URL source after switching projects', async () => {
    const creation = deferred<Document>();
    useStore.setState({ currentProject: project('project-1') });
    apiMock.createDocument.mockReturnValue(creation.promise);

    const pendingCreation = useStore.getState().createDocument('project-1', {
      name: 'Example',
      type: 'url',
      url: 'https://example.com',
    });
    useStore.getState().selectProject(project('project-2'));
    creation.resolve(readyDocument);
    await pendingCreation;

    expect(useStore.getState().documents).toEqual([]);
  });

  it('clears scoped state after deleting the current project', async () => {
    useStore.setState({
      projects: [project('project-1')],
      currentProject: project('project-1'),
      documents: [readyDocument],
      conversations: [conversation('conversation-1', 'project-1')],
      currentConversation: conversation('conversation-1', 'project-1'),
      messages: [authoritativeMessage],
    });
    apiMock.deleteProject.mockResolvedValue(undefined);

    await useStore.getState().deleteProject('project-1');

    expect(useStore.getState()).toEqual(expect.objectContaining({
      projects: [],
      currentProject: null,
      documents: [],
      conversations: [],
      currentConversation: null,
      messages: [],
    }));
  });

  it('deletes a document through the backend document route', async () => {
    useStore.setState({
      currentProject: project('project-1'),
      documents: [readyDocument],
    });
    apiMock.deleteDocument.mockResolvedValue(undefined);

    await useStore.getState().deleteDocument('project-1', 'document-1');

    expect(apiMock.deleteDocument).toHaveBeenCalledWith(
      'project-1',
      'document-1',
    );
    expect(useStore.getState().documents).toEqual([]);
  });

  it('stops simulated upload progress after a failed request', async () => {
    vi.useFakeTimers();
    apiMock.uploadDocument.mockRejectedValue(new Error('Upload failed'));

    await expect(
      useStore.getState().uploadDocument('project-1', new File(['pdf'], 'paper.pdf')),
    ).rejects.toThrow('Upload failed');
    await vi.advanceTimersByTimeAsync(400);

    expect(useStore.getState().uploadProgress).toEqual({});
    vi.useRealTimers();
  });

  it('uses the query endpoint and refreshes authoritative messages', async () => {
    useStore.setState({
      currentProject: project('project-1'),
      currentConversation: conversation('conversation-1', 'project-1'),
    });
    apiMock.query.mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: 'conversation-1',
    });
    apiMock.getMessages.mockResolvedValue([authoritativeMessage]);

    await useStore.getState().sendQuery('Question', true);

    expect(apiMock.query).toHaveBeenCalledWith({
      project_id: 'project-1',
      query: 'Question',
      conversation_id: 'conversation-1',
    });
    expect(apiMock.getMessages).toHaveBeenCalledWith('conversation-1');
    expect(useStore.getState().messages).toEqual([authoritativeMessage]);
  });

  it('does not reuse a conversation owned by another project', async () => {
    useStore.setState({
      currentProject: project('project-2'),
      currentConversation: conversation('conversation-1', 'project-1'),
    });
    const newConversation = conversation('conversation-2', 'project-2');
    apiMock.createConversation.mockResolvedValue(newConversation);
    apiMock.query.mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: 'conversation-2',
    });
    apiMock.getMessages.mockResolvedValue([]);

    await useStore.getState().sendQuery('Question');

    expect(apiMock.createConversation).toHaveBeenCalledWith(
      'project-2',
      'Question...',
    );
    expect(apiMock.query).toHaveBeenCalledWith(expect.objectContaining({
      project_id: 'project-2',
      conversation_id: 'conversation-2',
    }));
  });

  it('ignores stale messages after selecting another conversation', async () => {
    const messages = deferred<Message[]>();
    const firstConversation = conversation('conversation-1', 'project-1');
    const secondConversation = conversation('conversation-2', 'project-1');
    useStore.setState({
      currentProject: project('project-1'),
      currentConversation: firstConversation,
    });
    apiMock.getMessages.mockReturnValueOnce(messages.promise);

    const pendingMessages = useStore.getState().fetchMessages('conversation-1');
    apiMock.getMessages.mockResolvedValueOnce([]);
    await useStore.getState().selectConversation(secondConversation);
    messages.resolve([authoritativeMessage]);
    await pendingMessages;

    expect(useStore.getState().currentConversation).toEqual(secondConversation);
    expect(useStore.getState().messages).toEqual([]);
  });

  it('ignores a created conversation after switching projects', async () => {
    const creation = deferred<Conversation>();
    useStore.setState({ currentProject: project('project-1') });
    apiMock.createConversation.mockReturnValue(creation.promise);

    const pendingCreation = useStore.getState().createConversation(
      'project-1',
      'New chat',
    );
    useStore.getState().selectProject(project('project-2'));
    creation.resolve(conversation('conversation-1', 'project-1'));
    await pendingCreation;

    expect(useStore.getState().conversations).toEqual([]);
    expect(useStore.getState().currentConversation).toBeNull();
  });

  it('persists a conversation rename in the list and current selection', async () => {
    const original = conversation('conversation-1', 'project-1');
    const renamed = { ...original, title: 'Renamed chat' };
    useStore.setState({
      currentProject: project('project-1'),
      conversations: [original],
      currentConversation: original,
    });
    apiMock.updateConversation.mockResolvedValue(renamed);

    await useStore.getState().updateConversation(
      'conversation-1',
      'Renamed chat',
    );

    expect(apiMock.updateConversation).toHaveBeenCalledWith(
      'conversation-1',
      'Renamed chat',
    );
    expect(useStore.getState().conversations).toEqual([renamed]);
    expect(useStore.getState().currentConversation).toEqual(renamed);
  });
});
