import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import api, { Project, Document, Conversation, Message } from '@/lib/api';

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

// Initialize with demo data for development
const demoProject = {
  id: 'demo-project-1',
  name: 'Demo Project',
  description: 'Welcome to OpenNotebookLM! Upload documents to get started.',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const initialState = {
  projects: [demoProject],
  currentProject: demoProject,
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
            set({ projects, loadingProjects: false });
          } catch (error) {
            console.error('Failed to fetch projects:', error);
            set({ loadingProjects: false });
          }
        },
        
        selectProject: (project) => {
          set({ currentProject: project });
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
            set((state) => ({
              projects: state.projects.filter(p => p.id !== id),
              currentProject: state.currentProject?.id === id ? null : state.currentProject,
            }));
          } catch (error) {
            console.error('Failed to delete project:', error);
            throw error;
          }
        },
        
        // Documents
        fetchDocuments: async (projectId) => {
          set({ loadingDocuments: true });
          try {
            const documents = await api.getDocuments(projectId);
            set({ documents, loadingDocuments: false });
          } catch (error) {
            console.error('Failed to fetch documents:', error);
            set({ loadingDocuments: false });
          }
        },
        
        uploadDocument: async (projectId, file) => {
          const uploadId = `${projectId}-${file.name}-${Date.now()}`;
          set((state) => ({
            uploadProgress: { ...state.uploadProgress, [uploadId]: 0 },
          }));
          
          try {
            // Simulate progress updates
            const progressInterval = setInterval(() => {
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
            clearInterval(progressInterval);
            
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
          } catch (error) {
            console.error('Failed to upload document:', error);
            set((state) => {
              const { [uploadId]: _, ...rest } = state.uploadProgress;
              return { uploadProgress: rest };
            });
            throw error;
          }
        },
        
        createDocument: async (projectId, data) => {
          try {
            const document = await api.createDocument(projectId, data);
            set((state) => ({ documents: [...state.documents, document] }));
          } catch (error) {
            console.error('Failed to create document:', error);
            throw error;
          }
        },
        
        deleteDocument: async (projectId, documentId) => {
          try {
            await api.deleteDocument(projectId, documentId);
            set((state) => ({
              documents: state.documents.filter(d => d.id !== documentId),
            }));
          } catch (error) {
            console.error('Failed to delete document:', error);
            throw error;
          }
        },
        
        // Conversations
        fetchConversations: async (projectId) => {
          set({ loadingConversations: true });
          try {
            const conversations = await api.getConversations(projectId);
            set({ conversations, loadingConversations: false });
          } catch (error) {
            console.error('Failed to fetch conversations:', error);
            set({ loadingConversations: false });
          }
        },
        
        selectConversation: async (conversation) => {
          set({ currentConversation: conversation });
          await get().fetchMessages(conversation.id);
        },
        
        createConversation: async (projectId, title) => {
          try {
            const conversation = await api.createConversation(projectId, title);
            set((state) => ({
              conversations: [...state.conversations, conversation],
              currentConversation: conversation,
            }));
            return conversation;
          } catch (error) {
            console.error('Failed to create conversation:', error);
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
          set({ loadingMessages: true });
          try {
            const messages = await api.getMessages(conversationId);
            set({ messages, loadingMessages: false });
          } catch (error) {
            console.error('Failed to fetch messages:', error);
            set({ loadingMessages: false });
          }
        },
        
        // Query
        sendQuery: async (query, stream = false) => {
          const state = get();
          if (!state.currentProject) {
            throw new Error('No project selected');
          }
          
          // Create or use existing conversation
          let conversationId = state.currentConversation?.id;
          if (!conversationId) {
            const conversation = await state.createConversation(
              state.currentProject.id,
              query.substring(0, 50) + '...'
            );
            conversationId = conversation.id;
          }
          
          // Add user message
          const userMessage: Message = {
            id: `temp-${Date.now()}`,
            conversation_id: conversationId,
            role: 'user',
            content: query,
            created_at: new Date().toISOString(),
          };
          
          set((state) => ({ messages: [...state.messages, userMessage] }));
          
          if (stream) {
            // Streaming response
            const assistantMessage: Message = {
              id: `temp-${Date.now() + 1}`,
              conversation_id: conversationId,
              role: 'assistant',
              content: '',
              created_at: new Date().toISOString(),
            };
            
            set((state) => ({ messages: [...state.messages, assistantMessage] }));
            
            let fullContent = '';
            await api.streamQuery(
              {
                project_id: state.currentProject!.id,
                query,
                conversation_id: conversationId,
                stream: true,
              },
              (chunk) => {
                fullContent += chunk;
                set((state) => ({
                  messages: state.messages.map(msg =>
                    msg.id === assistantMessage.id
                      ? { ...msg, content: fullContent }
                      : msg
                  ),
                }));
              },
              () => {
                // Refresh messages to get server-side IDs
                get().fetchMessages(conversationId!);
              },
              (error) => {
                console.error('Stream query failed:', error);
              }
            );
          } else {
            // Non-streaming response
            try {
              const response = await api.query({
                project_id: state.currentProject.id,
                query,
                conversation_id: conversationId,
              });
              
              const assistantMessage: Message = {
                id: `temp-${Date.now() + 1}`,
                conversation_id: conversationId,
                role: 'assistant',
                content: response.answer,
                created_at: new Date().toISOString(),
              };
              
              set((state) => ({ messages: [...state.messages, assistantMessage] }));
              
              // Refresh messages to get server-side IDs
              await get().fetchMessages(conversationId);
            } catch (error) {
              console.error('Query failed:', error);
              throw error;
            }
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
