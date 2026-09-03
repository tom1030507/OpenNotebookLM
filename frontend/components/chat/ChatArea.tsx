'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  Send,
  Paperclip,
  Upload,
  FolderPlus,
  ChevronRight,
  Loader2
} from 'lucide-react';
import useStore, { QueryMessageRefreshError } from '@/store/useStore';
import {
  chatWorkspaceStyle,
  welcomeHeroStyles,
} from '@/components/desktopLayout';
import MarkdownRenderer from '../MarkdownRenderer';
import { requestAddSources } from '../sourceActions';
import type { Message } from '@/lib/api';
import BrandLogo from '../BrandLogo';
import { useOptionalProjectDialog } from '../ProjectDialogProvider';

interface ChatAreaProps {
  onAddSourcesOpenChange: (isOpen: boolean) => void;
}

interface PendingQuery {
  requestId: number;
  content: string;
  projectId: string;
  conversationId: string | null;
  error: string | null;
  retryMode: 'query' | 'refresh';
}

const MessageRow = React.memo(function MessageRow({ message }: { message: Message }) {
  return (
    <div className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      {message.role === 'assistant' && (
        <BrandLogo className="w-8 h-8 flex-shrink-0" />
      )}
      <div
        className={`max-w-[70%] ${
          message.role === 'user'
            ? 'bg-[var(--primary)] text-white'
            : 'bg-[var(--card)] border border-[var(--border)]'
        } rounded-lg px-4 py-3`}
      >
        {message.role === 'assistant' ? (
          <MarkdownRenderer content={message.content} />
        ) : (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        )}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            <p className="text-xs opacity-70 mb-2">Sources: </p>
            {message.citations.map((citation, index) => (
              <div key={index} className="mt-1 p-2 bg-[var(--muted)] rounded text-xs">
                <span className="font-medium">{citation.source}</span>
                {citation.page && <span className="opacity-70"> - page {citation.page}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
      {message.role === 'user' && (
        <div className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center flex-shrink-0">
          U
        </div>
      )}
    </div>
  );
});

export default function ChatArea({ onAddSourcesOpenChange }: ChatAreaProps) {
  const [inputValue, setInputValue] = useState('');
  const [pendingQuery, setPendingQuery] = useState<PendingQuery | null>(null);
  const nextRequestIdRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const projectDialog = useOptionalProjectDialog();
  
  const currentProject = useStore((state) => state.currentProject);
  const currentConversation = useStore((state) => state.currentConversation);
  const messages = useStore((state) => state.messages);
  const documents = useStore((state) => state.documents);
  const sendQuery = useStore((state) => state.sendQuery);
  const createConversation = useStore((state) => state.createConversation);
  const fetchMessages = useStore((state) => state.fetchMessages);
  const followMessageRead = useStore((state) => state.followMessageRead);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const submitQuery = async (query: string) => {
    if (!currentProject) return;

    const requestId = nextRequestIdRef.current + 1;
    nextRequestIdRef.current = requestId;
    setPendingQuery({
      requestId,
      content: query,
      projectId: currentProject.id,
      conversationId: currentConversation?.id ?? null,
      error: null,
      retryMode: 'query',
    });
    
    try {
      await sendQuery(query, false, (conversationId) => {
        setPendingQuery((pending) => (
          pending?.requestId === requestId
            ? { ...pending, conversationId }
            : pending
        ));
      });
    } catch (error) {
      console.error('Failed to send query:', error);
      const message = error instanceof Error ? error.message : 'Unable to send the question.';
      setPendingQuery((pending) => (
        pending?.requestId === requestId
          ? {
              ...pending,
              conversationId: error instanceof QueryMessageRefreshError
                ? error.conversationId
                : pending.conversationId,
              error: message,
              retryMode: error instanceof QueryMessageRefreshError ? 'refresh' : 'query',
            }
          : pending
      ));
      if (!(error instanceof QueryMessageRefreshError)) {
        // A reader can start composing another question while a request fails.
        // Do not overwrite that newer text with the failed question.
        setInputValue((value) => value || query);
      }
    } finally {
      setPendingQuery((pending) => (
        pending?.requestId === requestId && !pending.error ? null : pending
      ));
    }
  };

  const handleSend = () => {
    if (!inputValue.trim() || !currentProject) return;

    const query = inputValue.trim();
    setInputValue('');
    void submitQuery(query);
  };

  const retryPendingQuery = () => {
    if (!pendingQuery || !pendingQuery.error) return;

    if (pendingQuery.retryMode === 'refresh') {
      const { conversationId, requestId } = pendingQuery;
      if (!conversationId) return;

      setPendingQuery((pending) => (
        pending?.requestId === requestId ? { ...pending, error: null } : pending
      ));
      void (async () => {
        try {
          const refreshed = await fetchMessages(conversationId);
          const refreshStatus = await followMessageRead(refreshed);
          if (refreshStatus === 'failed') {
            throw new Error('The conversation could not be refreshed.');
          }
          setPendingQuery((pending) => (
            pending?.requestId === requestId ? null : pending
          ));
        } catch (error) {
          const message = error instanceof Error
            ? error.message
            : 'The conversation could not be refreshed.';
          setPendingQuery((pending) => (
            pending?.requestId === requestId
              ? { ...pending, error: message, retryMode: 'refresh' }
              : pending
          ));
        }
      })();
      return;
    }

    setInputValue('');
    void submitQuery(pendingQuery.content);
  };
  
  const handleNewConversation = async () => {
    if (!currentProject) return;
    
    try {
      await createConversation(currentProject.id, 'New Conversation');
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };
  
  // Check if ready to chat
  const hasDocuments = documents.length > 0 && documents.some(d => d.status === 'ready');
  const canChat = currentProject && hasDocuments;
  const canAddSources = Boolean(currentProject);
  const pendingQueryIsActive = pendingQuery !== null
    && pendingQuery.projectId === currentProject?.id
    && pendingQuery.conversationId === (currentConversation?.id ?? null);
  const isStreaming = pendingQueryIsActive && !pendingQuery.error;
  const hasPendingMessage = pendingQueryIsActive && !messages.some((message) => (
    message.role === 'user'
    && message.content === pendingQuery.content
    && message.conversation_id === pendingQuery.conversationId
  ));
  const visibleMessages = !hasPendingMessage
    ? messages
    : [
        ...messages,
        {
          id: 'pending-query',
          conversation_id: pendingQuery.conversationId || '',
          role: 'user' as const,
          content: pendingQuery.content,
          citations: [],
          created_at: '',
        },
      ];

  const handleRequestAddSources = () => {
    requestAddSources(canAddSources, onAddSourcesOpenChange);
  };

  return (
    <div
      data-layout="chat-workspace"
      className="min-w-0 flex-1 flex flex-col h-full bg-[var(--background)]"
      style={chatWorkspaceStyle}
    >
      {/* Chat Messages Area */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {visibleMessages.length === 0 ? (
          <div
            className="min-h-full flex flex-col items-center justify-center py-8"
            style={welcomeHeroStyles.frame}
          >
            {/* Welcome Screen */}
            <div
              data-layout="welcome-hero"
              className="text-center"
              style={welcomeHeroStyles.content}
            >
              <div
                data-layout="welcome-icon"
                className="mx-auto flex items-center justify-center"
                style={welcomeHeroStyles.icon}
              >
                <BrandLogo className="w-full h-full" />
              </div>
              
              <h2
                className="leading-tight font-normal mb-4"
                style={welcomeHeroStyles.title}
              >
                {currentProject
                  ? 'Add a source to get started'
                  : 'Create a project to get started'}
              </h2>
              
              <p className="max-w-2xl mx-auto text-base text-[var(--muted-foreground)] mb-8">
                {currentProject
                  ? 'NotebookLM can be inaccurate. Please verify its responses.'
                  : 'Projects keep your sources and conversations organized.'}
              </p>

              <button
                type="button"
                onClick={currentProject
                  ? handleRequestAddSources
                  : projectDialog?.openProjectDialog}
                disabled={!currentProject && !projectDialog}
                className="inline-flex items-center gap-2 px-6 py-3 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-base"
              >
                {currentProject ? (
                  <>
                    <Upload className="w-5 h-5" />
                    <span>Upload sources</span>
                  </>
                ) : (
                  <>
                  <FolderPlus className="w-5 h-5" />
                  <span>New Project</span>
                  </>
                )}
              </button>

              {currentProject && (
                <div
                  data-layout="welcome-actions"
                  className="grid text-left"
                  style={welcomeHeroStyles.actions}
                >
                  <div
                    className="bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer"
                    style={welcomeHeroStyles.card}
                  >
                    <h3 className="font-medium text-base mb-1.5">Quick start</h3>
                    <p className="text-sm text-[var(--muted-foreground)]">
                      Upload PDFs, web pages, or YouTube videos
                    </p>
                  </div>
                  <div
                    className="bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer"
                    style={welcomeHeroStyles.card}
                  >
                    <h3 className="font-medium text-base mb-1.5">Smart answers</h3>
                    <p className="text-sm text-[var(--muted-foreground)]">
                      Answers based on your documents
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="px-4 py-6">
            <div className="max-w-3xl mx-auto space-y-6">
              {visibleMessages.map((message) => (
                <MessageRow key={message.id} message={message} />
              ))}
              
              {isStreaming && (
                <div className="flex gap-3">
                  <BrandLogo className="w-8 h-8 flex-shrink-0" />
                  <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce" />
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce delay-100" />
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce delay-200" />
                    </div>
                  </div>
                </div>
              )}
              {pendingQueryIsActive && pendingQuery.error && (
                <div role="alert" className="flex items-center gap-3 text-sm text-[var(--error)]">
                  <span>{pendingQuery.error}</span>
                  <button
                    type="button"
                    onClick={retryPendingQuery}
                    className="text-[var(--primary)] hover:underline"
                  >
                    {pendingQuery.retryMode === 'refresh' ? 'Refresh response' : 'Retry question'}
                  </button>
                </div>
              )}
            </div>
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div
        data-layout="chat-composer"
        className={`border-t border-[var(--border)] bg-[var(--card)] ${currentProject ? 'p-4' : 'p-3'}`}
      >
        <div className="max-w-3xl mx-auto">
          <div className={`min-w-0 flex items-end ${currentProject ? 'gap-3' : 'gap-2'}`}>
            {currentProject && (
              <button
                onClick={handleRequestAddSources}
                aria-label={'Attach file'}
                title={'Attach file'}
                className="flex-shrink-0 p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-lg transition-base"
              >
                <Paperclip className="w-5 h-5" />
              </button>
            )}
            
            <div className="min-w-0 flex-1 relative">
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={
                  !currentProject
                    ? 'Create a project to start chatting'
                    : canChat
                      ? 'Ask anything about your sources...'
                      : 'Add sources to start chatting'
                }
                className="w-full px-4 py-3 bg-[var(--background)] border border-[var(--border)] rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base text-sm"
                rows={1}
                disabled={!canChat || isStreaming}
              />
              
              {inputValue && hasDocuments && (
                <span className="absolute right-3 bottom-2 text-xs text-[var(--muted-foreground)]">
                  {documents.filter(d => d.status === 'ready').length} sources
                </span>
              )}
            </div>
            
            <button
              onClick={handleSend}
              aria-label={'Send message'}
              title={'Send message'}
              disabled={!inputValue.trim() || !canChat || isStreaming}
              className={`flex-shrink-0 bg-[var(--accent)] text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-base ${currentProject ? 'p-3' : 'p-2.5'}`}>
              {isStreaming ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          
          {/* New Chat Button */}
          {messages.length > 0 && (
            <button 
              onClick={handleNewConversation}
              className="mt-3 flex items-center gap-1 text-xs text-[var(--primary)] hover:underline">
              <span>New Conversation</span>
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
