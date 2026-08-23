import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import api from '@/lib/api';
import type { Conversation, Document, Message, Project } from '@/lib/api';

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
  fetchMessages: (conversationId: string) => Promise<boolean>;
  
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

/**
 * Thwarts late responses from a prior signed-in account. This deliberately
 * lives outside Zustand so account transitions cannot be undone by an old
 * request replacing state wholesale.
 */
let accountEpoch = 0;

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
          const isCurrentAccount = () => accountEpoch === epoch;
          if (!isCurrentAccount()) return;
          set({ loadingProjects: true });
          try {
            const projects = await api.getProjects();
            if (!isCurrentAccount()) return;
            const previousProject = get().currentProject;
            const currentProject = projects.find(
              (project) => project.id === previousProject?.id,
            ) || projects[0] || null;
            const projectChanged = currentProject?.id !== previousProject?.id;

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

            if (currentProject && isCurrentAccount()) {
              await Promise.all([
                get().fetchDocuments(currentProject.id),
                get().fetchConversations(currentProject.id),
              ]);
            }
          } catch (error) {
            if (!isCurrentAccount()) return;
            console.error('Failed to fetch projects:', error);
            get().clearAccountState();
          }
        },
        
        selectProject: (project) => {
          set({
            currentProject: project,
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
            set((state) => ({ projects: [...state.projects, project] }));
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
            set((state) => {
              const deletedCurrentProject = state.currentProject?.id === id;
              return {
                projects: state.projects.filter(p => p.id !== id),
                currentProject: deletedCurrentProject ? null : state.currentProject,
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
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentProject?.id !== projectId) return;
          if (!isCurrentAccount()) return;
          set({ loadingDocuments: true });
          try {
            const documents = await api.getDocuments(projectId);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              set({ documents, loadingDocuments: false });
            }
          } catch (error) {
            if (!isCurrentAccount()) return;
            console.error('Failed to fetch documents:', error);
            if (get().currentProject?.id === projectId) {
              set({ loadingDocuments: false });
            }
          }
        },
        
        // The same fetch without the loading flag, so a source that is still
        // being indexed can be re-checked without flashing a spinner over the
        // list the reader is looking at.
        refreshDocuments: async (projectId, signal, shouldApply = () => true) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentProject?.id !== projectId) return;
          if (!isCurrentAccount()) return;
          try {
            const documents = await api.getDocuments(projectId, signal);
            if (
              isCurrentAccount()
              &&
              !signal?.aborted
              && shouldApply()
              && get().currentProject?.id === projectId
            ) {
              set({ documents });
            }
          } catch (error) {
            if (isCurrentAccount() && !signal?.aborted) {
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
              set((state) => ({
                documents: [...state.documents, document],
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
              set((state) => ({ documents: [...state.documents, document] }));
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
              set((state) => ({
                documents: state.documents.filter(d => d.id !== documentId),
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
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentProject?.id !== projectId) return;
          if (!isCurrentAccount()) return;
          set({ loadingConversations: true });
          try {
            const conversations = await api.getConversations(projectId);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              set({ conversations, loadingConversations: false });
            }
          } catch (error) {
            if (!isCurrentAccount()) return;
            console.error('Failed to fetch conversations:', error);
            if (get().currentProject?.id === projectId) {
              set({ loadingConversations: false });
            }
          }
        },
        
        selectConversation: async (conversation) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentProject?.id !== conversation.project_id) return;
          if (!isCurrentAccount()) return;
          set({ currentConversation: conversation, messages: [] });
          if (!isCurrentAccount()) return;
          await get().fetchMessages(conversation.id);
        },
        
        createConversation: async (projectId, title, select = true) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          try {
            const conversation = await api.createConversation(projectId, title);
            if (isCurrentAccount() && get().currentProject?.id === projectId) {
              set((state) => ({
                conversations: [...state.conversations, conversation],
                ...(select ? {
                  currentConversation: conversation,
                  messages: [],
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
              set((state) => ({
                conversations: state.conversations.map((item) => (
                  item.id === conversationId ? conversation : item
                )),
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
          try {
            await api.deleteConversation(conversationId);
            if (!isCurrentAccount()) return;
            set((state) => ({
              conversations: state.conversations.filter(c => c.id !== conversationId),
              currentConversation: state.currentConversation?.id === conversationId 
                ? null 
                : state.currentConversation,
              messages: state.currentConversation?.id === conversationId 
                ? [] 
                : state.messages,
            }));
          } catch (error) {
            if (isCurrentAccount()) console.error('Failed to delete conversation:', error);
            throw error;
          }
        },
        
        fetchMessages: async (conversationId) => {
          const epoch = accountEpoch;
          const isCurrentAccount = () => accountEpoch === epoch;
          if (get().currentConversation?.id !== conversationId) return false;
          if (!isCurrentAccount()) return false;
          set({ loadingMessages: true });
          try {
            const messages = await api.getMessages(conversationId);
            if (isCurrentAccount() && get().currentConversation?.id === conversationId) {
              set({ messages, loadingMessages: false });
              return true;
            }
            return false;
          } catch (error) {
            if (!isCurrentAccount()) return false;
            console.error('Failed to fetch messages:', error);
            if (get().currentConversation?.id === conversationId) {
              set({ loadingMessages: false });
            }
            return false;
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
              set({ currentConversation: conversation, messages: [] });
            }
          }

          if (!isCurrentAccount()) return;
          onConversationReady?.(conversationId);
          
          try {
            await api.query({
              project_id: projectId,
              query,
              conversation_id: conversationId,
            });
            if (!isCurrentAccount()) return;
            const refreshed = await get().fetchMessages(conversationId);
            if (!isCurrentAccount()) return;
            if (!refreshed) {
              if (get().currentConversation?.id !== conversationId) return;
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

export default useStore;
