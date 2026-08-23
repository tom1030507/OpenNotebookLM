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

const document = (id: string): Document => ({
  ...readyDocument,
  id,
  name: `Document ${id}`,
});

const message = (id: string, conversationId: string): Message => ({
  ...authoritativeMessage,
  id,
  conversation_id: conversationId,
  content: `Message ${id}`,
});


const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
};

const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
};


beforeEach(() => {
  vi.clearAllMocks();
  testStorage.clear();
  useStore.getState().resetForTests();
  apiMock.getDocuments.mockResolvedValue([]);
  apiMock.getConversations.mockResolvedValue([]);
  apiMock.getMessages.mockResolvedValue([]);
});


describe('application store', () => {
  it('resets test state to an empty project state instead of a fake backend id', () => {
    useStore.getState().resetForTests();

    expect(useStore.getState().projects).toEqual([]);
    expect(useStore.getState().currentProject).toBeNull();
  });

  it('does not return a project created by an account that has since cleared', async () => {
    const creation = deferred<Project>();
    apiMock.createProject.mockReturnValue(creation.promise);

    const pendingCreation = useStore.getState().createProject('Account A project');
    useStore.getState().clearAccountState();
    creation.resolve(project('project-a'));

    await expect(pendingCreation).resolves.toBeNull();
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

  it('retires project loading when selection supersedes a pending project read', async () => {
    const pendingProjects = deferred<Project[]>();
    apiMock.getProjects.mockReturnValue(pendingProjects.promise);

    const loadingProjects = useStore.getState().fetchProjects();
    useStore.getState().selectProject(project('project-b'));

    expect(useStore.getState().loadingProjects).toBe(false);
    pendingProjects.resolve([project('project-a')]);
    await loadingProjects;
    expect(useStore.getState().currentProject).toEqual(project('project-b'));
  });

  it('retires project loading when project creation supersedes a pending project read', async () => {
    const pendingProjects = deferred<Project[]>();
    const createdProject = project('project-created');
    apiMock.getProjects.mockReturnValue(pendingProjects.promise);
    apiMock.createProject.mockResolvedValue(createdProject);

    const loadingProjects = useStore.getState().fetchProjects();
    await expect(
      useStore.getState().createProject('Created project'),
    ).resolves.toEqual(createdProject);

    expect(useStore.getState().projects).toEqual([createdProject]);
    expect(useStore.getState().loadingProjects).toBe(false);
    pendingProjects.resolve([project('project-stale')]);
    await loadingProjects;
    expect(useStore.getState().projects).toEqual([createdProject]);
    expect(useStore.getState().loadingProjects).toBe(false);
  });

  it('ignores a document response for a project that is no longer selected', async () => {
    useStore.setState({ currentProject: project('project-2') });
    apiMock.getDocuments.mockResolvedValue([readyDocument]);

    await useStore.getState().fetchDocuments('project-1');

    expect(useStore.getState().documents).toEqual([]);
  });

  it('keeps newer documents after returning to the same project before an older read resolves', async () => {
    const projectA = project('project-a');
    const projectB = project('project-b');
    const firstAResponse = deferred<Document[]>();
    const bResponse = deferred<Document[]>();
    const secondAResponse = deferred<Document[]>();
    apiMock.getDocuments
      .mockReturnValueOnce(firstAResponse.promise)
      .mockReturnValueOnce(bResponse.promise)
      .mockReturnValueOnce(secondAResponse.promise);
    useStore.setState({ currentProject: projectA });

    const firstARequest = useStore.getState().fetchDocuments(projectA.id);
    useStore.getState().selectProject(projectB);
    useStore.getState().selectProject(projectA);

    secondAResponse.resolve([document('document-a2')]);
    await settle();
    bResponse.resolve([document('document-b')]);
    await settle();
    firstAResponse.resolve([document('document-a1')]);
    await firstARequest;

    expect(useStore.getState().documents).toEqual([document('document-a2')]);
    expect(useStore.getState().loadingDocuments).toBe(false);
  });

  it('retires document loading when source creation supersedes a pending document read', async () => {
    const currentProject = project('project-1');
    const pendingDocuments = deferred<Document[]>();
    const createdDocument = document('document-created');
    apiMock.getDocuments.mockReturnValue(pendingDocuments.promise);
    apiMock.createDocument.mockResolvedValue(createdDocument);
    useStore.setState({ currentProject, documents: [readyDocument] });

    const loadingDocuments = useStore.getState().fetchDocuments(currentProject.id);
    await useStore.getState().createDocument(currentProject.id, {
      name: createdDocument.name,
      type: 'url',
      url: 'https://example.com',
    });

    expect(useStore.getState().documents).toEqual([readyDocument, createdDocument]);
    expect(useStore.getState().loadingDocuments).toBe(false);
    pendingDocuments.resolve([document('document-stale')]);
    await loadingDocuments;
    expect(useStore.getState().documents).toEqual([readyDocument, createdDocument]);
    expect(useStore.getState().loadingDocuments).toBe(false);
  });

  it('keeps a polling document refresh newer than an earlier regular fetch', async () => {
    const regularResponse = deferred<Document[]>();
    const pollingResponse = deferred<Document[]>();
    const currentProject = project('project-1');
    apiMock.getDocuments
      .mockReturnValueOnce(regularResponse.promise)
      .mockReturnValueOnce(pollingResponse.promise);
    useStore.setState({ currentProject });

    const regularFetch = useStore.getState().fetchDocuments(currentProject.id);
    const pollingRefresh = useStore.getState().refreshDocuments(currentProject.id);
    pollingResponse.resolve([document('document-polling')]);
    await pollingRefresh;

    expect(useStore.getState().documents).toEqual([document('document-polling')]);
    expect(useStore.getState().loadingDocuments).toBe(false);

    regularResponse.resolve([document('document-regular')]);
    await regularFetch;

    expect(useStore.getState().documents).toEqual([document('document-polling')]);
    expect(useStore.getState().loadingDocuments).toBe(false);
  });

  it('keeps a newer regular document fetch when an earlier polling response arrives late', async () => {
    const pollingResponse = deferred<Document[]>();
    const regularResponse = deferred<Document[]>();
    const currentProject = project('project-1');
    apiMock.getDocuments
      .mockReturnValueOnce(pollingResponse.promise)
      .mockReturnValueOnce(regularResponse.promise);
    useStore.setState({ currentProject });

    const pollingRefresh = useStore.getState().refreshDocuments(currentProject.id);
    const regularFetch = useStore.getState().fetchDocuments(currentProject.id);
    regularResponse.resolve([document('document-regular')]);
    await regularFetch;
    pollingResponse.resolve([document('document-polling')]);
    await pollingRefresh;

    expect(useStore.getState().documents).toEqual([document('document-regular')]);
    expect(useStore.getState().loadingDocuments).toBe(false);
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

  it('does not report a query refresh failure when a newer message read supersedes it', async () => {
    const queryRefresh = deferred<Message[]>();
    const newerRefresh = deferred<Message[]>();
    const currentProject = project('project-1');
    const currentConversation = conversation('conversation-1', currentProject.id);
    apiMock.query.mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    apiMock.getMessages
      .mockReturnValueOnce(queryRefresh.promise)
      .mockReturnValueOnce(newerRefresh.promise);
    useStore.setState({ currentProject, currentConversation });

    const pendingQuery = useStore.getState().sendQuery('Question');
    await settle();
    const newerRead = useStore.getState().fetchMessages(currentConversation.id);
    newerRefresh.resolve([message('message-newer', currentConversation.id)]);
    await newerRead;
    queryRefresh.resolve([message('message-stale', currentConversation.id)]);

    await expect(pendingQuery).resolves.toBeUndefined();
    expect(useStore.getState().messages).toEqual([
      message('message-newer', currentConversation.id),
    ]);
    expect(useStore.getState().loadingMessages).toBe(false);
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

  it('does not replace a conversation selected while a query conversation is being created', async () => {
    const creation = deferred<Conversation>();
    const existingConversation = conversation('conversation-1', 'project-1');
    const createdConversation = conversation('conversation-2', 'project-1');
    const onConversationReady = vi.fn();
    useStore.setState({
      currentProject: project('project-1'),
      conversations: [existingConversation],
      currentConversation: null,
    });
    apiMock.createConversation.mockReturnValue(creation.promise);
    apiMock.query.mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: 'conversation-2',
    });
    apiMock.getMessages.mockResolvedValue([]);

    const pendingQuery = useStore.getState().sendQuery(
      'Question',
      false,
      onConversationReady,
    );
    useStore.setState({ currentConversation: existingConversation });
    creation.resolve(createdConversation);
    await pendingQuery;

    expect(onConversationReady).toHaveBeenCalledWith('conversation-2');
    expect(useStore.getState().currentConversation).toEqual(existingConversation);
    expect(useStore.getState().conversations).toEqual([
      existingConversation,
      createdConversation,
    ]);
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

  it('retires conversation loading when selecting a conversation supersedes its list read', async () => {
    const currentProject = project('project-1');
    const pendingConversations = deferred<Conversation[]>();
    apiMock.getConversations.mockReturnValue(pendingConversations.promise);
    useStore.setState({ currentProject });

    const loadingConversations = useStore.getState().fetchConversations(currentProject.id);
    await useStore.getState().selectConversation(
      conversation('conversation-1', currentProject.id),
    );

    expect(useStore.getState().loadingConversations).toBe(false);
    pendingConversations.resolve([conversation('conversation-stale', currentProject.id)]);
    await loadingConversations;
    expect(useStore.getState().conversations).toEqual([]);
  });

  it('keeps newer messages after returning to the same conversation before an older read resolves', async () => {
    const projectA = project('project-a');
    const conversationA = conversation('conversation-a', projectA.id);
    const conversationB = conversation('conversation-b', projectA.id);
    const firstAResponse = deferred<Message[]>();
    const bResponse = deferred<Message[]>();
    const secondAResponse = deferred<Message[]>();
    apiMock.getMessages
      .mockReturnValueOnce(firstAResponse.promise)
      .mockReturnValueOnce(bResponse.promise)
      .mockReturnValueOnce(secondAResponse.promise);
    useStore.setState({ currentProject: projectA, currentConversation: conversationA });

    const firstARequest = useStore.getState().fetchMessages(conversationA.id);
    const selectingB = useStore.getState().selectConversation(conversationB);
    const selectingA = useStore.getState().selectConversation(conversationA);
    secondAResponse.resolve([message('message-a2', conversationA.id)]);
    await selectingA;
    bResponse.resolve([message('message-b', conversationB.id)]);
    await selectingB;
    firstAResponse.resolve([message('message-a1', conversationA.id)]);
    await firstARequest;

    expect(useStore.getState().currentConversation).toEqual(conversationA);
    expect(useStore.getState().messages).toEqual([
      message('message-a2', conversationA.id),
    ]);
    expect(useStore.getState().loadingMessages).toBe(false);
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

  it('retires conversation loading when a rename supersedes a pending list read', async () => {
    const currentProject = project('project-1');
    const originalConversation = conversation('conversation-1', currentProject.id);
    const renamedConversation = { ...originalConversation, title: 'Renamed chat' };
    const pendingConversations = deferred<Conversation[]>();
    apiMock.getConversations.mockReturnValue(pendingConversations.promise);
    apiMock.updateConversation.mockResolvedValue(renamedConversation);
    useStore.setState({
      currentProject,
      conversations: [originalConversation],
      currentConversation: originalConversation,
    });

    const loadingConversations = useStore.getState().fetchConversations(currentProject.id);
    await useStore.getState().updateConversation(originalConversation.id, 'Renamed chat');

    expect(useStore.getState().conversations).toEqual([renamedConversation]);
    expect(useStore.getState().loadingConversations).toBe(false);
    pendingConversations.resolve([conversation('conversation-stale', currentProject.id)]);
    await loadingConversations;
    expect(useStore.getState().conversations).toEqual([renamedConversation]);
    expect(useStore.getState().loadingConversations).toBe(false);
  });

  it('keeps newer conversations after returning to the same project before an older read resolves', async () => {
    const projectA = project('project-a');
    const projectB = project('project-b');
    const firstAResponse = deferred<Conversation[]>();
    const bResponse = deferred<Conversation[]>();
    const secondAResponse = deferred<Conversation[]>();
    apiMock.getConversations
      .mockReturnValueOnce(firstAResponse.promise)
      .mockReturnValueOnce(bResponse.promise)
      .mockReturnValueOnce(secondAResponse.promise);
    useStore.setState({ currentProject: projectA });

    const firstARequest = useStore.getState().fetchConversations(projectA.id);
    useStore.getState().selectProject(projectB);
    useStore.getState().selectProject(projectA);

    secondAResponse.resolve([conversation('conversation-a2', projectA.id)]);
    await settle();
    bResponse.resolve([conversation('conversation-b', projectB.id)]);
    await settle();
    firstAResponse.resolve([conversation('conversation-a1', projectA.id)]);
    await firstARequest;

    expect(useStore.getState().conversations).toEqual([
      conversation('conversation-a2', projectA.id),
    ]);
    expect(useStore.getState().loadingConversations).toBe(false);
  });

  it('keeps a newer project list when an older same-account refresh resolves last', async () => {
    const firstResponse = deferred<Project[]>();
    const secondResponse = deferred<Project[]>();
    apiMock.getProjects
      .mockReturnValueOnce(firstResponse.promise)
      .mockReturnValueOnce(secondResponse.promise);

    const firstRequest = useStore.getState().fetchProjects();
    const secondRequest = useStore.getState().fetchProjects();
    secondResponse.resolve([project('project-a2')]);
    await secondRequest;
    firstResponse.resolve([project('project-a1')]);
    await firstRequest;

    expect(useStore.getState().projects).toEqual([project('project-a2')]);
    expect(useStore.getState().currentProject).toEqual(project('project-a2'));
    expect(useStore.getState().loadingProjects).toBe(false);
  });
});
