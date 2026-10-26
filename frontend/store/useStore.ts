import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import api from '@/lib/api';
import type {
  Conversation,
  Citation,
  Document,
  Message,
  MessageRating,
  Project,
  ProjectMergeMode,
  ProjectMergeResponse,
  StreamQueryResponse,
} from '@/lib/api';
import { registerAccountStateRetirer } from '@/lib/sessionBoundary';

interface StudyRoundScore {
  correct: number;
  total: number;
  elapsedSeconds: number;
  completedAt: string;
}

interface AppState {
  // Projects
  projects: Project[];
  currentProject: Project | null;
  loadingProjects: boolean;
  
  // Documents
  documents: Document[];
  loadingDocuments: boolean;
  uploadProgress: { [key: string]: number };
  /**
   * Sources left out of questions and Studio outputs, per project id. The
   * deselected ids are kept rather than the selected ones so a source added
   * later is included by default.
   */
  deselectedSources: Record<string, string[]>;
  
  // Conversations
  conversations: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  loadingConversations: boolean;
  loadingMessages: boolean;
  
  // UI State
  sidebarOpen: boolean;
  studioOpen: boolean;
  pendingMindMapQuestion: { projectId: string; question: string } | null;
  citationPreview: { document: Document; citation: Citation } | null;

  // Preferences
  /** Whether finishing a source announces itself. Read by useDocumentStatusWatch. */
  notifyOnProcessingComplete: boolean;

  // Study progress
  studyScoresByProject: Record<string, StudyRoundScore[]>;

  // Actions - Projects
  fetchProjects: () => Promise<void>;
  selectProject: (project: Project) => void;
  createProject: (name?: string, description?: string) => Promise<Project | null>;
  updateProject: (id: string, data: {
    name?: string;
    description?: string;
    cover_emoji?: string | null;
    cover_color?: string | null;
  }) => Promise<Project | null>;
  updateProjectTags: (id: string, tags: string[]) => Promise<void>;
  duplicateProject: (id: string) => Promise<Project | null>;
  mergeProject: (
    sourceId: string,
    targetId: string,
    mode: ProjectMergeMode,
  ) => Promise<ProjectMergeResponse | null>;
  deleteProject: (id: string) => Promise<void>;
  
  // Actions - Documents
  fetchDocuments: (projectId: string) => Promise<void>;
  refreshDocuments: (
    projectId: string,
    signal?: AbortSignal,
    shouldApply?: () => boolean,
  ) => Promise<void>;
  uploadDocument: (projectId: string, file: File) => Promise<void>;
  createDocument: (projectId: string, data: {
    name: string;
    type: 'url' | 'youtube' | 'text';
    content?: string;
    url?: string;
  }) => Promise<void>;
  deleteDocument: (projectId: string, documentId: string) => Promise<void>;
  renameDocument: (documentId: string, title: string) => Promise<void>;
  rateMessage: (
    conversationId: string,
    messageId: string,
    rating: MessageRating,
  ) => Promise<void>;

  toggleSourceSelected: (projectId: string, documentId: string) => void;
  setSourcesSelected: (projectId: string, documentIds: string[], selected: boolean) => void;
  setAllSourcesSelected: (projectId: string, selected: boolean) => void;
  
  // Actions - Conversations
  fetchConversations: (projectId: string) => Promise<void>;
  selectConversation: (conversation: Conversation) => Promise<void>;
  beginNewConversation: () => void;
  createConversation: (
    projectId: string,
    title?: string,
    select?: boolean,
  ) => Promise<Conversation>;
  updateConversation: (conversationId: string, title: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  fetchMessages: (conversationId: string) => Promise<MessageFetchResult>;
  followMessageRead: (initialResult: MessageFetchResult) => Promise<MessageFetchStatus>;
  
  // Actions - Query
  sendQuery: (
    query: string,
    stream?: boolean,
    onConversationReady?: (conversationId: string) => void,
    options?: {
      signal?: AbortSignal;
      onToken?: (token: string) => void;
      onComplete?: (response: StreamQueryResponse) => void;
      model?: string;
    },
  ) => Promise<void>;
  
  // Actions - UI
  toggleSidebar: () => void;
  toggleStudio: () => void;
  draftMindMapQuestion: (projectId: string, question: string) => void;
  consumeMindMapQuestion: (projectId: string) => string | null;
  openCitationPreview: (citation: Citation) => boolean;
  clearCitationPreview: () => void;

  // Actions - Preferences
  setNotifyOnProcessingComplete: (enabled: boolean) => void;

  // Actions - Study progress
  /**
   * Record one completed quick round for its project.
   * Args:
   *   projectId: Project whose history should receive the score.
   *   score: Correct answers, total questions, elapsed time, and completion time.
   * Returns:
   *   Nothing.
   */
  recordStudyScore: (projectId: string, score: StudyRoundScore) => void;

  // Account boundary
  clearAccountState: () => void;
  resetForTests: () => void;
}

/** The authoritative message read either applied, genuinely failed, or was retired. */
type MessageFetchStatus = 'applied' | 'failed' | 'stale';

interface MessageFetchResult {
  status: MessageFetchStatus;
  epoch: number;
  generation: number;
  projectId: string | null;
  conversationId: string;
}

interface MessageReadAuthority {
  epoch: number;
  generation: number;
  projectId: string;
  conversationId: string;
  completion: Promise<MessageFetchResult>;
  settle: (result: MessageFetchResult) => void;
  retirement: Promise<void>;
  retire: () => void;
}

/**
 * Thwarts late responses from a prior signed-in account. This deliberately
 * lives outside Zustand so account transitions cannot be undone by an old
 * request replacing state wholesale.
 */
let accountEpoch = 0;

/**
 * A project can be selected again before its first request returns. Account
 * epochs cannot distinguish that A1 → B → A2 sequence, so each rendered
 * resource keeps its own authority counter as well.
 */
const readGenerations = {
  projects: 0,
  documents: 0,
  conversations: 0,
  messages: 0,
};

type ReadResource = keyof typeof readGenerations;

const advanceReadGeneration = (resource: ReadResource): number => {
  if (resource === 'messages') {
    retireActiveMessageRead();
  }
  readGenerations[resource] += 1;
  return readGenerations[resource];
};

const retireProjectScopedReads = (): void => {
  advanceReadGeneration('documents');
  advanceReadGeneration('conversations');
  advanceReadGeneration('messages');
};

const retireAllReads = (): void => {
  advanceReadGeneration('projects');
  retireProjectScopedReads();
};

const isCurrentRead = (
  resource: ReadResource,
  generation: number,
  epoch: number,
): boolean => accountEpoch === epoch && readGenerations[resource] === generation;

let activeMessageRead: MessageReadAuthority | null = null;

const createMessageReadAuthority = (
  epoch: number,
  generation: number,
  projectId: string,
  conversationId: string,
): MessageReadAuthority => {
  let resolveCompletion!: (result: MessageFetchResult) => void;
  let resolveRetirement!: () => void;
  let settled = false;
  let retired = false;
  const completion = new Promise<MessageFetchResult>((completionResolve) => {
    resolveCompletion = completionResolve;
  });
  const retirement = new Promise<void>((retirementResolve) => {
    resolveRetirement = retirementResolve;
  });

  return {
    epoch,
    generation,
    projectId,
    conversationId,
    completion,
    settle: (result) => {
      if (settled) return;
      settled = true;
      resolveCompletion(result);
    },
    retirement,
    retire: () => {
      if (retired) return;
      retired = true;
      resolveRetirement();
    },
  };
};

const messageFetchResult = (
  status: MessageFetchStatus,
  epoch: number,
  generation: number,
  projectId: string | null,
  conversationId: string,
): MessageFetchResult => ({
  status,
  epoch,
  generation,
  projectId,
  conversationId,
});

/**
 * The message transport has no AbortSignal, so retiring an authority must
 * settle both its followers and its direct caller before a later read wins.
 */
const retireActiveMessageRead = (): void => {
  const authority = activeMessageRead;
  if (!authority) return;

  activeMessageRead = null;
  authority.retire();
  authority.settle(messageFetchResult(
    'stale',
    authority.epoch,
    authority.generation,
    authority.projectId,
    authority.conversationId,
  ));
};

/** Signals that the query mutation finished but its authoritative refresh did not. */
export class QueryMessageRefreshError extends Error {
  conversationId: string;

  constructor(conversationId: string) {
    super('The question was sent, but the conversation could not be refreshed.');
    this.name = 'QueryMessageRefreshError';
    this.conversationId = conversationId;
  }
}

const initialState = {
  projects: [],
  currentProject: null,
  loadingProjects: false,
  documents: [],
  loadingDocuments: false,
  uploadProgress: {},
  deselectedSources: {},
  conversations: [],
  currentConversation: null,
  messages: [],
  loadingConversations: false,
  loadingMessages: false,
  sidebarOpen: true,
  studioOpen: true,
  pendingMindMapQuestion: null,
  citationPreview: null,
  notifyOnProcessingComplete: true,
  studyScoresByProject: {},
};

/**
 * The source ids to scope a question or Studio output to.
 *
 * `undefined` while every source is selected, so the request goes out exactly
 * as it did before sources could be deselected; `[]` when none is, which
 * callers treat as "cannot send" rather than as "search everything".
 */
export const selectedSourceIds = (
  state: Pick<AppState, 'currentProject' | 'documents' | 'deselectedSources'>,
): string[] | undefined => {
  const deselected = state.deselectedSources[state.currentProject?.id ?? ''] ?? [];
  const selectable = state.documents.filter((doc) => doc.status !== 'error');
  const selected = selectable
    .filter((doc) => !deselected.includes(doc.id))
    .map((doc) => doc.id);
  return selected.length === selectable.length ? undefined : selected;
};

const useStore = create<AppState>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,
        
        // Projects
        fetchProjects: async () => {
          const epoch = accountEpoch;
          const generation = advanceReadGeneration('projects');
          const isCurrentRequest = () => isCurrentRead('projects', generation, epoch);
          if (!isCurrentRequest()) return;
          set({ loadingProjects: true });
          try {
            const projects = await api.getProjects();
            if (!isCurrentRequest()) return;
            const previousProject = get().currentProject;
            const currentProject = projects.find(
              (project) => project.id === previousProject?.id,
            ) || projects[0] || null;
            const projectChanged = currentProject?.id !== previousProject?.id;

            if (!currentProject || projectChanged) {
              retireProjectScopedReads();
            }
            if (!isCurrentRequest()) return;

            set({
              projects,
              currentProject,
              loadingProjects: false,
              ...(!currentProject || projectChanged ? {
                pendingMindMapQuestion: null,
                citationPreview: null,
                documents: [],
                conversations: [],
                currentConversation: null,
                messages: [],
                loadingDocuments: false,
                loadingConversations: false,
                loadingMessages: false,
              } : {}),
            });

            if (currentProject && isCurrentRequest()) {
              await Promise.all([
                get().fetchDocuments(currentProject.id),
                get().fetchConversations(currentProject.id),
              ]);
            }
          } catch (error) {
            if (!isCurrentRequest()) return;
            console.error('Failed to fetch projects:', error);
            get().clearAccountState();
          }
        },
        
        selectProject: (project) => {
          advanceReadGeneration('projects');
          retireProjectScopedReads();
          set({
            currentProject: project,
            pendingMindMapQuestion: null,
            citationPreview: null,
            loadingProjects: false,
            documents: [],
            conversations: [],
            currentConversation: null,
            messages: [],
            loadingDocuments: false,
            loadingConversations: false,
            loadingMessages: false,
          });
          // Fetch documents and conversations for the selected project
          get().fetchDocuments(project.id);
          get().fetchConversations(project.id);
        },
        
        createProject: async (name, description) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            const project = await api.createProject({ name, description });
            if (!isCurrentAccount()) return null;
            advanceReadGeneration('projects');
            set((state) => ({
              projects: [...state.projects, project],
              loadingProjects: false,
            }));
            return project;
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to create project:', error);
            throw error;
          }
        },

        updateProject: async (id, data) => {
          const epoch = accountEpoch;
          try {
            const project = await api.updateProject(id, data);
            if (accountEpoch !== epoch) return null;
            advanceReadGeneration('projects');
            set((state) => ({
              projects: state.projects.map((item) => item.id === id ? project : item),
              currentProject: state.currentProject?.id === id ? project : state.currentProject,
            }));
            return project;
          } catch (error) {
            if (accountEpoch === epoch) console.error('Failed to update project:', error);
            throw error;
          }
        },

        updateProjectTags: async (id, tags) => {
          const epoch = accountEpoch;
          try {
            const savedTags = await api.updateProjectTags(id, tags);
            if (accountEpoch !== epoch) return;
            set((state) => ({
              projects: state.projects.map((project) => (
                project.id === id ? { ...project, tags: savedTags } : project
              )),
              currentProject: state.currentProject?.id === id
                ? { ...state.currentProject, tags: savedTags }
                : state.currentProject,
            }));
          } catch (error) {
            if (accountEpoch === epoch) console.error('Failed to update project tags:', error);
            throw error;
          }
        },

        duplicateProject: async (id) => {
          const epoch = accountEpoch;
          try {
            const project = await api.duplicateProject(id);
            if (accountEpoch !== epoch) return null;
            advanceReadGeneration('projects');
            set((state) => ({
              projects: [...state.projects, project],
              loadingProjects: false,
            }));
            return project;
          } catch (error) {
            if (accountEpoch === epoch) console.error('Failed to duplicate project:', error);
            throw error;
          }
        },

        mergeProject: async (sourceId, targetId, mode) => {
          const epoch = accountEpoch;
          try {
            const result = await api.mergeProject(sourceId, targetId, mode);
            if (accountEpoch !== epoch) return null;
            const target = get().projects.find((project) => project.id === targetId);
            if (target) get().selectProject(target);
            void get().fetchProjects();
            return result;
          } catch (error) {
            if (accountEpoch === epoch) console.error('Failed to merge projects:', error);
            throw error;
          }
        },
        
        deleteProject: async (id) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            await api.deleteProject(id);
            if (!isCurrentAccount()) return;
            const deletedCurrentProject = get().currentProject?.id === id;
            advanceReadGeneration('projects');
            if (deletedCurrentProject) {
              retireProjectScopedReads();
            }
            set((state) => {
              return {
                projects: state.projects.filter(p => p.id !== id),
                currentProject: deletedCurrentProject ? null : state.currentProject,
                loadingProjects: false,
                ...(deletedCurrentProject ? {
                  pendingMindMapQuestion: null,
                  documents: [],
                  conversations: [],
                  currentConversation: null,
                  messages: [],
                  loadingDocuments: false,
                  loadingConversations: false,
                  loadingMessages: false,
                } : {}),
              };
            });
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to delete project:', error);
            throw error;
          }
        },
        
        // Documents
        fetchDocuments: async (projectId) => {
          const epoch = accountEpoch;
          if (get().currentProject?.id !== projectId) return;
          if (accountEpoch !== epoch) return;
          const generation = advanceReadGeneration('documents');
          const isCurrentRequest = () => isCurrentRead('documents', generation, epoch)
            && get().currentProject?.id === projectId;
          if (!isCurrentRequest()) return;
          set({ loadingDocuments: true });
          try {
            const documents = await api.getDocuments(projectId);
            if (isCurrentRequest()) {
              set({ documents, loadingDocuments: false });
            }
          } catch (error) {
            if (!isCurrentRequest()) return;
            console.error('Failed to fetch documents:', error);
            set({ loadingDocuments: false });
          }
        },
        
        // The same fetch without the loading flag, so a source that is still
        // being indexed can be re-checked without flashing a spinner over the
        // list the reader is looking at.
        refreshDocuments: async (projectId, signal, shouldApply = () => true) => {
          const epoch = accountEpoch;
          if (get().currentProject?.id !== projectId) return;
          if (accountEpoch !== epoch) return;
          const generation = advanceReadGeneration('documents');
          const isCurrentRequest = () => isCurrentRead('documents', generation, epoch)
            && get().currentProject?.id === projectId;
          if (!isCurrentRequest()) return;
          if (get().loadingDocuments) {
            set({ loadingDocuments: false });
          }
          try {
            const documents = await api.getDocuments(projectId, signal);
            if (
              isCurrentRequest()
              &&
              !signal?.aborted
              && shouldApply()
            ) {
              set({ documents });
            }
          } catch (error) {
            if (isCurrentRequest() && !signal?.aborted) {
              console.error('Failed to refresh documents:', error);
            }
          }
        },

        uploadDocument: async (projectId, file) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          if (!isCurrentAccount()) return;
          const uploadId = `${projectId}-${file.name}-${Date.now()}`;
          let progressInterval: ReturnType<typeof setInterval> | undefined;
          set((state) => ({
            uploadProgress: { ...state.uploadProgress, [uploadId]: 0 },
          }));
          
          try {
            // Simulate progress updates
            progressInterval = setInterval(() => {
              if (!isCurrentAccount()) {
                if (progressInterval) clearInterval(progressInterval);
                return;
              }
              set((state) => {
                const currentProgress = state.uploadProgress[uploadId] || 0;
                if (currentProgress < 90) {
                  return {
                    uploadProgress: {
                      ...state.uploadProgress,
                      [uploadId]: currentProgress + 10,
                    },
                  };
                }
                return state;
              });
            }, 200);
            
            const document = await api.uploadDocument(projectId, file);
            const isCurrentProject = isCurrentAccount()
              && get().currentProject?.id === projectId;

            if (isCurrentProject) {
              advanceReadGeneration('documents');
              set((state) => ({
                documents: [...state.documents, document],
                loadingDocuments: false,
                uploadProgress: { ...state.uploadProgress, [uploadId]: 100 },
              }));

              // Clean up progress after a delay
              setTimeout(() => {
                if (!isCurrentAccount()) return;
                set((state) => {
                  const { [uploadId]: _, ...rest } = state.uploadProgress;
                  return { uploadProgress: rest };
                });
              }, 1000);
            } else if (isCurrentAccount()) {
              set((state) => {
                const { [uploadId]: _, ...rest } = state.uploadProgress;
                return { uploadProgress: rest };
              });
            }
          } catch (error) {
            if (isCurrentAccount()) {
              console.error('Failed to upload document:', error);
              set((state) => {
                const { [uploadId]: _, ...rest } = state.uploadProgress;
                return { uploadProgress: rest };
              });
            }
            throw error;
          } finally {
            if (progressInterval) {
              clearInterval(progressInterval);
            }
          }
        },
        
        createDocument: async (projectId, data) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            const document = await api.createDocument(projectId, data);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              advanceReadGeneration('documents');
              set((state) => ({
                documents: [...state.documents, document],
                loadingDocuments: false,
              }));
            }
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to create document:', error);
            throw error;
          }
        },
        
        deleteDocument: async (projectId, documentId) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            await api.deleteDocument(projectId, documentId);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              advanceReadGeneration('documents');
              set((state) => ({
                documents: state.documents.filter(d => d.id !== documentId),
                loadingDocuments: false,
              }));
            }
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to delete document:', error);
            throw error;
          }
        },

        renameDocument: async (documentId, title) => {
          const epoch = accountEpoch;
          const document = await api.renameDocument(documentId, title);
          if (accountEpoch !== epoch) return;
          advanceReadGeneration('documents');
          // The backend rewrites stored citations too; patch the loaded answers
          // so they show the new title without a reload.
          set((state) => ({
            documents: state.documents.map((item) => (
              item.id === documentId ? document : item
            )),
            loadingDocuments: false,
            messages: state.messages.map((message) => (
              message.citations?.some((citation) => citation.document_id === documentId)
                ? {
                  ...message,
                  citations: message.citations.map((citation) => (
                    citation.document_id === documentId
                      ? { ...citation, source: document.name, document_title: document.name }
                      : citation
                  )),
                }
                : message
            )),
          }));
        },

        rateMessage: async (conversationId, messageId, rating) => {
          const epoch = accountEpoch;
          await api.rateMessage(conversationId, messageId, rating);
          if (accountEpoch !== epoch) return;
          set((state) => ({
            messages: state.messages.map((message) => (
              message.id === messageId ? { ...message, rating } : message
            )),
          }));
        },

        
        toggleSourceSelected: (projectId, documentId) => {
          set((state) => {
            const deselected = state.deselectedSources[projectId] ?? [];
            return {
              deselectedSources: {
                ...state.deselectedSources,
                [projectId]: deselected.includes(documentId)
                  ? deselected.filter((id) => id !== documentId)
                  : [...deselected, documentId],
              },
            };
          });
        },

        setSourcesSelected: (projectId, documentIds, selected) => {
          const sourceIds = new Set(documentIds);
          set((state) => ({
            deselectedSources: {
              ...state.deselectedSources,
              [projectId]: selected
                ? (state.deselectedSources[projectId] ?? []).filter((id) => !sourceIds.has(id))
                : [...new Set([...(state.deselectedSources[projectId] ?? []), ...documentIds])],
            },
          }));
        },

        setAllSourcesSelected: (projectId, selected) => {
          set((state) => ({
            deselectedSources: {
              ...state.deselectedSources,
              [projectId]: selected ? [] : state.documents
                .filter((doc) => doc.status !== 'error')
                .map((doc) => doc.id),
            },
          }));
        },
        
        // Conversations
        fetchConversations: async (projectId) => {
          const epoch = accountEpoch;
          if (get().currentProject?.id !== projectId) return;
          if (accountEpoch !== epoch) return;
          const generation = advanceReadGeneration('conversations');
          const isCurrentRequest = () => isCurrentRead('conversations', generation, epoch)
            && get().currentProject?.id === projectId;
          if (!isCurrentRequest()) return;
          set({ loadingConversations: true });
          try {
            const conversations = await api.getConversations(projectId);
            if (isCurrentRequest()) {
              set({ conversations, loadingConversations: false });
            }
          } catch (error) {
            if (!isCurrentRequest()) return;
            console.error('Failed to fetch conversations:', error);
            set({ loadingConversations: false });
          }
        },
        
        selectConversation: async (conversation) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentProject?.id !== conversation.project_id) return;
          if (!isCurrentAccount()) return;
          advanceReadGeneration('conversations');
          advanceReadGeneration('messages');
          set({
            currentConversation: conversation,
            messages: [],
            loadingConversations: false,
            loadingMessages: false,
          });
          if (!isCurrentAccount()) return;
          await get().fetchMessages(conversation.id);
        },

        beginNewConversation: () => {
          advanceReadGeneration('messages');
          set({
            currentConversation: null,
            messages: [],
            loadingMessages: false,
          });
        },
        
        createConversation: async (projectId, title, select = true) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            const conversation = await api.createConversation(projectId, title);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              advanceReadGeneration('conversations');
              if (select) {
                advanceReadGeneration('messages');
              }
              set((state) => ({
                conversations: [conversation, ...state.conversations],
                loadingConversations: false,
                ...(select ? {
                  currentConversation: conversation,
                  messages: [],
                  loadingMessages: false,
                } : {}),
              }));
            }
            return conversation;
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to create conversation:', error);
            throw error;
          }
        },

        updateConversation: async (conversationId, title) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            const conversation = await api.updateConversation(conversationId, title);
            if (isCurrentAccount() && get().currentProject?.id === conversation.project_id) {
              advanceReadGeneration('conversations');
              set((state) => ({
                conversations: state.conversations.map((item) => (
                  item.id === conversationId ? conversation : item
                )),
                loadingConversations: false,
                currentConversation: state.currentConversation?.id === conversationId
                  ? conversation
                  : state.currentConversation,
              }));
            }
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to update conversation:', error);
            throw error;
          }
        },
        
        deleteConversation: async (conversationId) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          const state = get();
          const initiatingConversation = state.conversations.find(
            (conversation) => conversation.id === conversationId,
          ) ?? (
            state.currentConversation?.id === conversationId
              ? state.currentConversation
              : null
          );
          const initiatingProjectId = initiatingConversation?.project_id;
          const isCurrentProject = () => initiatingProjectId !== undefined
            && get().currentProject?.id === initiatingProjectId;
          try {
            await api.deleteConversation(conversationId);
            if (!isCurrentAccount() || !isCurrentProject()) return;
            const deletedCurrentConversation = get().currentConversation?.id === conversationId;
            advanceReadGeneration('conversations');
            if (deletedCurrentConversation) {
              advanceReadGeneration('messages');
            }
            set((state) => ({
              conversations: state.conversations.filter(c => c.id !== conversationId),
              loadingConversations: false,
              currentConversation: deletedCurrentConversation
                ? null 
                : state.currentConversation,
              messages: deletedCurrentConversation
                ? [] 
                : state.messages,
              ...(deletedCurrentConversation ? { loadingMessages: false } : {}),
            }));
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to delete conversation:', error);
            throw error;
          }
        },
        
        fetchMessages: async (conversationId) => {
          const epoch = accountEpoch;
          const projectId = get().currentProject?.id ?? null;
          const staleResult = () => messageFetchResult(
            'stale',
            epoch,
            readGenerations.messages,
            projectId,
            conversationId,
          );
          if (!projectId || get().currentConversation?.id !== conversationId) {
            return staleResult();
          }
          if (accountEpoch !== epoch) return staleResult();
          const generation = advanceReadGeneration('messages');
          const isCurrentRequest = () => isCurrentRead('messages', generation, epoch)
            && get().currentProject?.id === projectId
            && get().currentConversation?.id === conversationId;
          if (!isCurrentRequest()) return staleResult();
          const authority = createMessageReadAuthority(
            epoch,
            generation,
            projectId,
            conversationId,
          );
          activeMessageRead = authority;
          const complete = (status: MessageFetchStatus) => {
            const result = messageFetchResult(
              status,
              epoch,
              generation,
              projectId,
              conversationId,
            );
            authority.settle(result);
            return result;
          };
          set({ loadingMessages: true });
          try {
            const messages = await Promise.race([
              api.getMessages(conversationId),
              authority.retirement.then(() => null),
            ]);
            if (messages === null) return complete('stale');
            if (isCurrentRequest()) {
              set({ messages, loadingMessages: false });
              return complete('applied');
            }
            return complete('stale');
          } catch (error) {
            if (!isCurrentRequest()) return complete('stale');
            console.error('Failed to fetch messages:', error);
            set({ loadingMessages: false });
            return complete('failed');
          }
        },

        followMessageRead: async (initialResult) => {
          const { epoch, projectId, conversationId } = initialResult;
          const isCurrentContext = () => (
            projectId !== null
            && accountEpoch === epoch
            && get().currentProject?.id === projectId
            && get().currentConversation?.id === conversationId
          );
          let result = initialResult;

          while (result.status === 'stale') {
            if (!isCurrentContext()) return 'stale';
            const successor = activeMessageRead;
            if (
              !successor
              || successor.epoch !== epoch
              || successor.projectId !== projectId
              || successor.conversationId !== conversationId
              || successor.generation <= result.generation
            ) {
              return 'stale';
            }
            result = await successor.completion;
          }

          return isCurrentContext() ? result.status : 'stale';
        },
        
        // Query
        sendQuery: async (query, stream = false, onConversationReady, options) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          const state = get();
          if (!isCurrentAccount() || !state.currentProject) {
            throw new Error('No project selected');
          }

          const projectId = state.currentProject.id;
          const startingMessagesGeneration = readGenerations.messages;
          const startingConversationId = state.currentConversation?.project_id
            === projectId
            ? state.currentConversation.id
            : null;
          
          // Create or use existing conversation
          let conversationId = startingConversationId ?? undefined;
          if (!conversationId) {
            const conversation = await state.createConversation(
              projectId,
              Array.from(query).slice(0, 100).join(''),
              false,
            );
            conversationId = conversation.id;
            if (!isCurrentAccount()) return;

            const activeState = get();
            const activeConversationId = activeState.currentConversation?.project_id
              === projectId
              ? activeState.currentConversation.id
              : null;
            if (
              isCurrentAccount()
              &&
              activeState.currentProject?.id === projectId
              && activeConversationId === startingConversationId
              // A second new-chat action also leaves the conversation id null.
              && readGenerations.messages === startingMessagesGeneration
            ) {
              advanceReadGeneration('messages');
              set({
                currentConversation: conversation,
                messages: [],
                loadingMessages: false,
              });
            }
          }

          if (!isCurrentAccount()) return;
          onConversationReady?.(conversationId);
          const isCurrentQueryContext = () => (
            isCurrentAccount()
            && get().currentProject?.id === projectId
            && get().currentConversation?.id === conversationId
          );
          
          try {
            const request = {
              project_id: projectId,
              query,
              conversation_id: conversationId,
              document_ids: selectedSourceIds(get()),
              ...(options?.model ? { model: options.model } : {}),
            };
            if (stream) {
              const response = await api.streamQuery(request, options?.signal, options?.onToken);
              options?.onComplete?.(response);
            } else {
              await api.query(request);
            }
            if (!isCurrentAccount()) return;
            const refreshed = await get().fetchMessages(conversationId);
            if (!isCurrentAccount()) return;
            const refreshStatus = await get().followMessageRead(refreshed);
            if (!isCurrentAccount()) return;
            if (refreshStatus === 'failed') {
              if (!isCurrentQueryContext()) return;
              throw new QueryMessageRefreshError(conversationId);
            }
          } catch (error) {
            if (isCurrentAccount() && !(error instanceof Error && error.name === 'AbortError')) {
              console.error('Query failed:', error);
            }
            throw error;
          }
        },
        
        // UI
        toggleSidebar: () => {
          set((state) => ({ sidebarOpen: !state.sidebarOpen }));
        },
        
        toggleStudio: () => {
          set((state) => ({ studioOpen: !state.studioOpen }));
        },

        draftMindMapQuestion: (projectId, question) => {
          const content = question.trim();
          if (get().currentProject?.id !== projectId || !content) return;
          set({
            pendingMindMapQuestion: { projectId, question: content },
            sidebarOpen: false,
            studioOpen: false,
          });
        },

        consumeMindMapQuestion: (projectId) => {
          const { currentProject, pendingMindMapQuestion } = get();
          if (currentProject?.id !== projectId || pendingMindMapQuestion?.projectId !== projectId) {
            return null;
          }
          set({ pendingMindMapQuestion: null });
          return pendingMindMapQuestion.question;
        },

        openCitationPreview: (citation) => {
          const document = get().documents.find(
            (item) => item.id === citation.document_id,
          );
          if (!document) return false;
          set({ citationPreview: { document, citation } });
          return true;
        },

        clearCitationPreview: () => set({ citationPreview: null }),

        // Preferences
        setNotifyOnProcessingComplete: (enabled) => {
          set({ notifyOnProcessingComplete: enabled });
        },
        recordStudyScore: (projectId, score) => set((state) => ({
          studyScoresByProject: {
            ...state.studyScoresByProject,
            // shortcut: keep five recent rounds per project; raise this if users need a longer history.
            [projectId]: [score, ...(state.studyScoresByProject[projectId] ?? [])].slice(0, 5),
          },
        })),

        // Account boundary
        clearAccountState: () => {
          accountEpoch += 1;
          retireAllReads();
          set((state) => ({
            projects: [],
            currentProject: null,
            pendingMindMapQuestion: null,
            citationPreview: null,
            loadingProjects: false,
            documents: [],
            loadingDocuments: false,
            uploadProgress: {},
            deselectedSources: {},
            conversations: [],
            currentConversation: null,
            messages: [],
            loadingConversations: false,
            loadingMessages: false,
            sidebarOpen: state.sidebarOpen,
            studioOpen: state.studioOpen,
            notifyOnProcessingComplete: state.notifyOnProcessingComplete,
            studyScoresByProject: {},
          }));
        },
        resetForTests: () => {
          accountEpoch += 1;
          retireAllReads();
          set(initialState);
        },
      }),
      {
        name: 'app-storage',
        partialize: (state) => ({
          sidebarOpen: state.sidebarOpen,
          studioOpen: state.studioOpen,
          notifyOnProcessingComplete: state.notifyOnProcessingComplete,
          studyScoresByProject: state.studyScoresByProject,
        }),
      }
    )
  )
);

registerAccountStateRetirer(() => {
  useStore.getState().clearAccountState();
});

export default useStore;
