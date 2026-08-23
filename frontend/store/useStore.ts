import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import api from '@/lib/api';
import type { Conversation, Document, Message, Project } from '@/lib/api';
import { registerAccountStateRetirer } from '@/lib/sessionBoundary';

interface AppState {
  // Projects
  projects: Project[];
  currentProject: Project | null;
  loadingProjects: boolean;
  
  // Documents
  documents: Document[];
  loadingDocuments: boolean;
  uploadProgress: { [key: string]: number };
  
  // Conversations
  conversations: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  loadingConversations: boolean;
  loadingMessages: boolean;
  
  // UI State
  sidebarOpen: boolean;
  studioOpen: boolean;

  // Preferences
  /** Whether finishing a source announces itself. Read by useDocumentStatusWatch. */
  notifyOnProcessingComplete: boolean;

  // Actions - Projects
  fetchProjects: () => Promise<void>;
  selectProject: (project: Project) => void;
  createProject: (name: string, description?: string) => Promise<Project | null>;
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
  
  // Actions - Conversations
  fetchConversations: (projectId: string) => Promise<void>;
  selectConversation: (conversation: Conversation) => Promise<void>;
  createConversation: (
    projectId: string,
    title?: string,
    select?: boolean,
  ) => Promise<Conversation>;
  updateConversation: (conversationId: string, title: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  fetchMessages: (conversationId: string) => Promise<MessageFetchResult>;
  
  // Actions - Query
  sendQuery: (
    query: string,
    stream?: boolean,
    onConversationReady?: (conversationId: string) => void,
  ) => Promise<void>;
  
  // Actions - UI
  toggleSidebar: () => void;
  toggleStudio: () => void;

  // Actions - Preferences
  setNotifyOnProcessingComplete: (enabled: boolean) => void;

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
  resolve: (result: MessageFetchResult) => void;
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
  let resolve!: (result: MessageFetchResult) => void;
  const completion = new Promise<MessageFetchResult>((completionResolve) => {
    resolve = completionResolve;
  });

  return {
    epoch,
    generation,
    projectId,
    conversationId,
    completion,
    resolve,
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
  conversations: [],
  currentConversation: null,
  messages: [],
  loadingConversations: false,
  loadingMessages: false,
  sidebarOpen: true,
  studioOpen: true,
  notifyOnProcessingComplete: true,
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
                conversations: [...state.conversations, conversation],
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
            authority.resolve(result);
            return result;
          };
          set({ loadingMessages: true });
          try {
            const messages = await api.getMessages(conversationId);
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
        
        // Query
        sendQuery: async (query, stream = false, onConversationReady) => {
          void stream;
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          const state = get();
          if (!isCurrentAccount() || !state.currentProject) {
            throw new Error('No project selected');
          }

          const projectId = state.currentProject.id;
          const startingConversationId = state.currentConversation?.project_id
            === projectId
            ? state.currentConversation.id
            : null;
          
          // Create or use existing conversation
          let conversationId = startingConversationId ?? undefined;
          if (!conversationId) {
            const conversation = await state.createConversation(
              projectId,
              query.substring(0, 50) + '...',
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
          const followMessageRead = async (
            initialResult: MessageFetchResult,
          ): Promise<MessageFetchStatus> => {
            let result = initialResult;

            while (result.status === 'stale') {
              if (!isCurrentQueryContext()) return 'stale';
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

            return result.status;
          };
          
          try {
            await api.query({
              project_id: projectId,
              query,
              conversation_id: conversationId,
            });
            if (!isCurrentAccount()) return;
            const refreshed = await get().fetchMessages(conversationId);
            if (!isCurrentAccount()) return;
            const refreshStatus = await followMessageRead(refreshed);
            if (!isCurrentAccount()) return;
            if (refreshStatus === 'failed') {
              if (!isCurrentQueryContext()) return;
              throw new QueryMessageRefreshError(conversationId);
            }
          } catch (error) {
            if (isCurrentAccount()) console.error('Query failed:', error);
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

        // Preferences
        setNotifyOnProcessingComplete: (enabled) => {
          set({ notifyOnProcessingComplete: enabled });
        },

        // Account boundary
        clearAccountState: () => {
          accountEpoch += 1;
          retireAllReads();
          activeMessageRead = null;
          set((state) => ({
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
            sidebarOpen: state.sidebarOpen,
            studioOpen: state.studioOpen,
            notifyOnProcessingComplete: state.notifyOnProcessingComplete,
          }));
        },
        resetForTests: () => {
          accountEpoch += 1;
          retireAllReads();
          activeMessageRead = null;
          set(initialState);
        },
      }),
      {
        name: 'app-storage',
        partialize: (state) => ({
          sidebarOpen: state.sidebarOpen,
          studioOpen: state.studioOpen,
          notifyOnProcessingComplete: state.notifyOnProcessingComplete,
        }),
      }
    )
  )
);

registerAccountStateRetirer(() => {
  useStore.getState().clearAccountState();
});

export default useStore;
