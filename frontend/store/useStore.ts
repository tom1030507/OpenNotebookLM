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
  
  // Actions - Projects
  fetchProjects: () => Promise<void>;
  selectProject: (project: Project) => void;
  createProject: (name: string, description?: string) => Promise<Project>;
  deleteProject: (id: string) => Promise<void>;
  
  // Actions - Documents
  fetchDocuments: (projectId: string) => Promise<void>;
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
  createConversation: (projectId: string, title?: string) => Promise<Conversation>;
  updateConversation: (conversationId: string, title: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  fetchMessages: (conversationId: string) => Promise<void>;
  
  // Actions - Query
  sendQuery: (query: string, stream?: boolean) => Promise<void>;
  
  // Actions - UI
  toggleSidebar: () => void;
  toggleStudio: () => void;
  
  // Reset
  reset: () => void;
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
};

const useStore = create<AppState>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,
        
        // Projects
        fetchProjects: async () => {
          set({ loadingProjects: true });
          try {
            const projects = await api.getProjects();
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

            if (currentProject) {
              await Promise.all([
                get().fetchDocuments(currentProject.id),
                get().fetchConversations(currentProject.id),
              ]);
            }
          } catch (error) {
            console.error('Failed to fetch projects:', error);
            set({ loadingProjects: false });
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
          try {
            const project = await api.createProject({ name, description });
            set((state) => ({ projects: [...state.projects, project] }));
            return project;
          } catch (error) {
            console.error('Failed to create project:', error);
            throw error;
          }
        },
        
        deleteProject: async (id) => {
          try {
            await api.deleteProject(id);
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
            console.error('Failed to delete project:', error);
            throw error;
          }
        },
        
        // Documents
        fetchDocuments: async (projectId) => {
          if (get().currentProject?.id !== projectId) return;
          set({ loadingDocuments: true });
          try {
            const documents = await api.getDocuments(projectId);
            if (get().currentProject?.id === projectId) {
              set({ documents, loadingDocuments: false });
            }
          } catch (error) {
            console.error('Failed to fetch documents:', error);
            if (get().currentProject?.id === projectId) {
              set({ loadingDocuments: false });
            }
          }
        },
        
        uploadDocument: async (projectId, file) => {
          const uploadId = `${projectId}-${file.name}-${Date.now()}`;
          let progressInterval: ReturnType<typeof setInterval> | undefined;
          set((state) => ({
            uploadProgress: { ...state.uploadProgress, [uploadId]: 0 },
          }));
          
          try {
            // Simulate progress updates
            progressInterval = setInterval(() => {
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
            const isCurrentProject = get().currentProject?.id === projectId;

            if (isCurrentProject) {
              set((state) => ({
                documents: [...state.documents, document],
                uploadProgress: { ...state.uploadProgress, [uploadId]: 100 },
              }));

              // Clean up progress after a delay
              setTimeout(() => {
                set((state) => {
                  const { [uploadId]: _, ...rest } = state.uploadProgress;
                  return { uploadProgress: rest };
                });
              }, 1000);
            } else {
              set((state) => {
                const { [uploadId]: _, ...rest } = state.uploadProgress;
                return { uploadProgress: rest };
              });
            }
          } catch (error) {
            console.error('Failed to upload document:', error);
            set((state) => {
              const { [uploadId]: _, ...rest } = state.uploadProgress;
              return { uploadProgress: rest };
            });
            throw error;
          } finally {
            if (progressInterval) {
              clearInterval(progressInterval);
            }
          }
        },
        
        createDocument: async (projectId, data) => {
          try {
            const document = await api.createDocument(projectId, data);
            if (get().currentProject?.id === projectId) {
              set((state) => ({ documents: [...state.documents, document] }));
            }
          } catch (error) {
            console.error('Failed to create document:', error);
            throw error;
          }
        },
        
        deleteDocument: async (projectId, documentId) => {
          try {
            await api.deleteDocument(projectId, documentId);
            if (get().currentProject?.id === projectId) {
              set((state) => ({
                documents: state.documents.filter(d => d.id !== documentId),
              }));
            }
          } catch (error) {
            console.error('Failed to delete document:', error);
            throw error;
          }
        },
        
        // Conversations
        fetchConversations: async (projectId) => {
          if (get().currentProject?.id !== projectId) return;
          set({ loadingConversations: true });
          try {
            const conversations = await api.getConversations(projectId);
            if (get().currentProject?.id === projectId) {
              set({ conversations, loadingConversations: false });
            }
          } catch (error) {
            console.error('Failed to fetch conversations:', error);
            if (get().currentProject?.id === projectId) {
              set({ loadingConversations: false });
            }
          }
        },
        
        selectConversation: async (conversation) => {
          if (get().currentProject?.id !== conversation.project_id) return;
          set({ currentConversation: conversation, messages: [] });
          await get().fetchMessages(conversation.id);
        },
        
        createConversation: async (projectId, title) => {
          try {
            const conversation = await api.createConversation(projectId, title);
            if (get().currentProject?.id === projectId) {
              set((state) => ({
                conversations: [...state.conversations, conversation],
                currentConversation: conversation,
                messages: [],
              }));
            }
            return conversation;
          } catch (error) {
            console.error('Failed to create conversation:', error);
            throw error;
          }
        },

        updateConversation: async (conversationId, title) => {
          try {
            const conversation = await api.updateConversation(conversationId, title);
            if (get().currentProject?.id === conversation.project_id) {
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
            console.error('Failed to update conversation:', error);
            throw error;
          }
        },
        
        deleteConversation: async (conversationId) => {
          try {
            await api.deleteConversation(conversationId);
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
            console.error('Failed to delete conversation:', error);
            throw error;
          }
        },
        
        fetchMessages: async (conversationId) => {
          if (get().currentConversation?.id !== conversationId) return;
          set({ loadingMessages: true });
          try {
            const messages = await api.getMessages(conversationId);
            if (get().currentConversation?.id === conversationId) {
              set({ messages, loadingMessages: false });
            }
          } catch (error) {
            console.error('Failed to fetch messages:', error);
            if (get().currentConversation?.id === conversationId) {
              set({ loadingMessages: false });
            }
          }
        },
        
        // Query
        sendQuery: async (query, stream = false) => {
          void stream;
          const state = get();
          if (!state.currentProject) {
            throw new Error('No project selected');
          }
          
          // Create or use existing conversation
          let conversationId = state.currentConversation?.project_id
            === state.currentProject.id
            ? state.currentConversation.id
            : undefined;
          if (!conversationId) {
            const conversation = await state.createConversation(
              state.currentProject.id,
              query.substring(0, 50) + '...'
            );
            conversationId = conversation.id;
          }
          
          try {
            await api.query({
              project_id: state.currentProject.id,
              query,
              conversation_id: conversationId,
            });
            await get().fetchMessages(conversationId);
          } catch (error) {
            console.error('Query failed:', error);
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
        
        // Reset
        reset: () => {
          set(initialState);
        },
      }),
      {
        name: 'app-storage',
        partialize: (state) => ({
          sidebarOpen: state.sidebarOpen,
          studioOpen: state.studioOpen,
        }),
      }
    )
  )
);

export default useStore;
