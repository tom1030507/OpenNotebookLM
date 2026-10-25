'use client';

import React, { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react';
import { 
  Send,
  Paperclip,
  Upload,
  FolderPlus,
  ChevronRight,
  MessageSquare,
  Loader2,
  SlidersHorizontal,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';
import useStore, { QueryMessageRefreshError, selectedSourceIds } from '@/store/useStore';
import {
  chatWorkspaceStyle,
  welcomeHeroStyles,
} from '@/components/desktopLayout';
import MarkdownRenderer from '../MarkdownRenderer';
import { requestAddSources } from '../sourceActions';
import type { Message } from '@/lib/api';
import { citationId, referencedCitationIds } from '@/lib/citations';
import BrandLogo from '../BrandLogo';
import { useOptionalProjectDialog } from '../ProjectDialogProvider';
import ChatSettingsDialog from './ChatSettingsDialog';
import SaveToNoteButton from './SaveToNoteButton';
import { FollowUpQuestions, ProjectOverview } from './SuggestedQuestions';

interface ChatAreaProps {
  onAddSourcesOpenChange: (isOpen: boolean) => void;
  outputLanguageRevision?: number;
  onOutputLanguageChanged?: () => void;
}

interface PendingQuery {
  requestId: number;
  content: string;
  projectId: string;
  conversationId: string | null;
  error: string | null;
  retryMode: 'query' | 'refresh';
}

const COMPOSER_MAX_HEIGHT = 160;

/** The signed-in account's initial, so the asker's mark is theirs rather than a generic "U". */
function accountInitial(): string {
  try {
    const raw = typeof window === 'undefined' ? null : window.localStorage.getItem('user');
    const username = raw ? (JSON.parse(raw) as { username?: string }).username : undefined;
    return username?.trim().charAt(0).toUpperCase() || 'U';
  } catch {
    return 'U';
  }
}

function AnswerRating({ message }: { message: Message }) {
  const rateMessage = useStore((state) => state.rateMessage);
  const rate = (rating: 'up' | 'down') => {
    // Choosing the rating already given clears it.
    rateMessage(
      message.conversation_id,
      message.id,
      message.rating === rating ? null : rating,
    ).catch((error) => console.error('Failed to rate answer:', error));
  };
  // The chosen rating has to read at a glance in a near-black UI: a filled
  // glyph on the selection tone, not just ink against grey.
  const buttonClass = (active: boolean) => `p-1 rounded transition-base ${
    active
      ? 'bg-[var(--accent-bg)] text-[var(--foreground)]'
      : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]'
  }`;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => rate('up')}
        aria-label="Good answer"
        title="Good answer"
        aria-pressed={message.rating === 'up'}
        className={buttonClass(message.rating === 'up')}
      >
        <ThumbsUp className="w-3.5 h-3.5" fill={message.rating === 'up' ? 'currentColor' : 'none'} />
      </button>
      <button
        type="button"
        onClick={() => rate('down')}
        aria-label="Bad answer"
        title="Bad answer"
        aria-pressed={message.rating === 'down'}
        className={buttonClass(message.rating === 'down')}
      >
        <ThumbsDown className="w-3.5 h-3.5" fill={message.rating === 'down' ? 'currentColor' : 'none'} />
      </button>
    </div>
  );
}

const MessageRow = React.memo(function MessageRow({ message }: { message: Message }) {
  const referencedIds = React.useMemo(
    () => referencedCitationIds(message.content, message.citations ?? []),
    [message.content, message.citations],
  );
  const citations = (message.citations ?? []).map((citation, index) => ({
    citation,
    index,
    id: citationId(citation),
  })).filter(({ id }) => (
    // Older messages lack source numbers; guessing from position could attach
    // evidence to the wrong claim, so retain those entries without a number.
    referencedIds.size === 0 || id === null || referencedIds.has(id)
  ));
  const citationLabels = new Map<number, number>();
  if (referencedIds.size > 0) {
    citations.forEach(({ id }) => {
      if (id !== null && !citationLabels.has(id)) {
        citationLabels.set(id, citationLabels.size + 1);
      }
    });
  }
  const citationGroups = citations.reduce<Array<{
    key: string;
    source: string;
    entries: typeof citations;
  }>>((groups, entry) => {
    const source = entry.citation.source || 'Unknown source';
    const key = String(entry.citation.document_id || source);
    let group = groups.find((candidate) => candidate.key === key);
    if (!group) {
      group = { key, source, entries: [] };
      groups.push(group);
    }
    group.entries.push(entry);
    return groups;
  }, []);

  return (
    <div className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      {message.role === 'assistant' && (
        <BrandLogo className="w-8 h-8 flex-shrink-0" />
      )}
      <div
        className={`${
          message.role === 'user'
            // The question sits on the neutral selection tone: a near-black
            // block would outweigh the answer, which is what the reader came for.
            ? 'max-w-[85%] bg-[var(--accent-bg)] text-[var(--foreground)]'
            // An answer fills the column rather than 70% of it. The cap left a
            // gutter as wide as the composer's right third, and on a 1024px
            // screen with the side panels open it squeezed the prose to about
            // 250px while 110px next to it stayed empty.
            : 'min-w-0 flex-1 bg-[var(--card)] border border-[var(--border)]'
        } rounded-lg px-4 py-3`}
      >
        {message.role === 'assistant' ? (
          <MarkdownRenderer
            content={message.content}
            citations={message.citations}
            citationLabels={citationLabels}
            citationChecks={message.citation_checks}
          />
        ) : (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        )}
        {citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            <p className="text-xs opacity-70 mb-2">Sources: </p>
            {citationGroups.map(({ key, source, entries }) => (
              <div key={key} className="mt-1 p-2 bg-[var(--muted)] rounded text-xs break-words">
                <p className="font-medium">{source}</p>
                {entries.map(({ citation, id, index }) => {
                  const excerpt = citation.text?.replace(/\s+/g, ' ').trim();
                  const displayId = id === null ? null : citationLabels.get(id) ?? id;
                  const label = (
                    <>
                      {displayId !== null && (
                        <span className="font-medium mr-2 text-[var(--accent)]">[{displayId}]</span>
                      )}
                      {citation.page != null && <span className="opacity-70">page {citation.page}</span>}
                      {displayId === null && citation.page == null && <span>Passage</span>}
                    </>
                  );

                  return excerpt ? (
                    <details key={id === null ? `legacy-${index}` : `source-${id}`} className="mt-1">
                      <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-[var(--ring)]">
                        {label}
                      </summary>
                      <p className="mt-2 leading-relaxed text-[var(--muted-foreground)]">{excerpt}</p>
                    </details>
                  ) : (
                    <div key={id === null ? `legacy-${index}` : `source-${id}`} className="mt-1">
                      {label}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
        {message.role === 'assistant' && (
          <div className="mt-2 flex items-center gap-1">
            <SaveToNoteButton message={message} />
            <AnswerRating message={message} />
          </div>
        )}
      </div>
      {message.role === 'user' && (
        <div
          aria-hidden="true"
          className="w-8 h-8 rounded-full bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] text-sm font-medium flex items-center justify-center flex-shrink-0"
        >
          {accountInitial()}
        </div>
      )}
    </div>
  );
});

export default function ChatArea({
  onAddSourcesOpenChange,
  outputLanguageRevision = 0,
  onOutputLanguageChanged,
}: ChatAreaProps) {
  const [inputValue, setInputValue] = useState('');
  const [pendingQuery, setPendingQuery] = useState<PendingQuery | null>(null);
  const [showChatSettings, setShowChatSettings] = useState(false);
  // Follow-ups cost a model call, so they are offered for answers given in this
  // session rather than regenerated every time an old conversation is opened.
  const [followUpConversationId, setFollowUpConversationId] = useState<string | null>(null);
  const nextRequestIdRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const composerGenerationRef = useRef(0);
  const resizeComposer = useCallback(() => {
    const composer = composerRef.current;
    if (!composer) return;
    composer.style.height = 'auto';
    const height = composer.scrollHeight;
    composer.style.height = `${Math.min(height, COMPOSER_MAX_HEIGHT)}px`;
    composer.style.overflowY = height > COMPOSER_MAX_HEIGHT ? 'auto' : 'hidden';
  }, []);
  const projectDialog = useOptionalProjectDialog();
  
  const currentProject = useStore((state) => state.currentProject);
  // Until the first project list (or a project's source list) arrives there is
  // no telling an empty account or project from a full one; showing "Create a
  // project" or "Add a source" in that gap told a returning reader, for a
  // second or two, that their work was gone.
  const awaitingProjects = useStore((state) => state.loadingProjects && !state.currentProject);
  // Only for a project known to hold sources: a new or empty one goes straight
  // to "Add a source", which is also where creation hands focus.
  const awaitingSources = useStore((state) => (
    (state.currentProject?.document_count ?? 0) > 0
      && state.loadingDocuments
      && state.documents.length === 0
  ));
  const currentConversation = useStore((state) => state.currentConversation);
  const messages = useStore((state) => state.messages);
  const documents = useStore((state) => state.documents);
  const selectedSourceCount = useStore((state) => {
    const selectedIds = selectedSourceIds(state);
    return selectedIds?.length
      ?? state.documents.filter((document) => document.status !== 'error').length;
  });
  const noSourcesSelected = selectedSourceCount === 0;
  const sendQuery = useStore((state) => state.sendQuery);
  const beginNewConversation = useStore((state) => state.beginNewConversation);
  const fetchMessages = useStore((state) => state.fetchMessages);
  const followMessageRead = useStore((state) => state.followMessageRead);
  const pendingMindMapQuestion = useStore((state) => state.pendingMindMapQuestion);
  const consumeMindMapQuestion = useStore((state) => state.consumeMindMapQuestion);

  useLayoutEffect(() => {
    resizeComposer();
  }, [inputValue, resizeComposer]);

  useEffect(() => {
    window.addEventListener('resize', resizeComposer);
    return () => window.removeEventListener('resize', resizeComposer);
  }, [resizeComposer]);

  useEffect(() => useStore.subscribe((state, previous) => {
    // Observe each transition so even a batched A → B → A cannot retain a
    // question from the previous project or signed-in account.
    if (state.currentProject?.id !== previous.currentProject?.id) {
      composerGenerationRef.current += 1;
      setInputValue('');
    }
  }), []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const submitQuery = async (query: string) => {
    if (!currentProject || noSourcesSelected) return;

    const composerGeneration = composerGenerationRef.current;
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
      setFollowUpConversationId(useStore.getState().currentConversation?.id ?? null);
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
      if (!(error instanceof QueryMessageRefreshError)
        && composerGenerationRef.current === composerGeneration) {
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
    if (!inputValue.trim() || !currentProject || noSourcesSelected) return;

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
  
  const handleNewConversation = () => {
    if (!currentProject) return;

    beginNewConversation();
  };
  
  // Check if ready to chat
  const readyDocumentIds = documents.filter(d => d.status === 'ready').map(d => d.id);
  const readyDocumentCount = readyDocumentIds.length;
  const hasDocuments = readyDocumentCount > 0;
  const canChat = currentProject && hasDocuments;
  const canEditProject = currentProject?.role === 'owner' || currentProject?.role === 'editor';
  const canAddSources = Boolean(currentProject && canEditProject);
  const pendingQueryIsActive = pendingQuery !== null
    && pendingQuery.projectId === currentProject?.id
    && pendingQuery.conversationId === (currentConversation?.id ?? null);
  const isStreaming = pendingQueryIsActive && !pendingQuery.error;

  useEffect(() => {
    if (!pendingMindMapQuestion || !currentProject || !canChat || noSourcesSelected || isStreaming) return;

    // Dialog and drawer cleanup restores their trigger first; focusing in the
    // next frame keeps that cleanup from stealing focus back from the composer.
    const frame = requestAnimationFrame(() => {
      const question = consumeMindMapQuestion(currentProject.id);
      if (question === null) return;
      setInputValue((value) => value.trim() ? `${value}\n\n${question}` : question);
      composerRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [pendingMindMapQuestion, currentProject, canChat, noSourcesSelected, isStreaming, consumeMindMapQuestion]);

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
  const lastMessage = visibleMessages[visibleMessages.length - 1];

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
        {awaitingProjects || (awaitingSources && visibleMessages.length === 0) ? (
          <div className="min-h-full flex items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]" role="status">
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            {awaitingProjects ? 'Loading your projects…' : 'Loading sources…'}
          </div>
        ) : visibleMessages.length === 0 ? (
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
                className="leading-tight font-semibold tracking-tight mb-3"
                style={welcomeHeroStyles.title}
              >
                {!currentProject
                  ? 'Create a project to get started'
                  : hasDocuments
                    ? 'Ask anything about your sources'
                    : canAddSources ? 'Add a source to get started' : 'Waiting for a project source'}
              </h2>

              <p className="max-w-2xl mx-auto text-sm text-[var(--muted-foreground)] mb-6">
                {!currentProject
                  ? 'Projects keep your sources and conversations organized.'
                  : hasDocuments
                    ? 'OpenNotebookLM can be inaccurate. Please verify its responses.'
                    : canAddSources
                      ? 'Answers are grounded in the sources you add, and cite them.'
                      : 'Ask the project owner or an editor to add a source.'}
              </p>

              {currentProject && hasDocuments && (
                <ProjectOverview
                  projectId={currentProject.id}
                  readySourceKey={readyDocumentIds.sort().join(',')}
                  outputLanguageRevision={outputLanguageRevision}
                  disabled={noSourcesSelected}
                  onAsk={(question) => void submitQuery(question)}
                />
              )}

              <button
                type="button"
                onClick={!currentProject
                  ? projectDialog ? () => projectDialog.openProjectDialog() : undefined
                  : hasDocuments
                    ? () => composerRef.current?.focus()
                    : canAddSources ? handleRequestAddSources : undefined}
                disabled={(!currentProject && !projectDialog)
                  || (Boolean(currentProject) && !hasDocuments && !canAddSources)}
                className="inline-flex items-center gap-2 h-9 px-4 text-sm font-medium bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-base"
              >
                {!currentProject ? (
                  <>
                    <FolderPlus className="w-5 h-5" />
                    <span>New Project</span>
                  </>
                ) : hasDocuments ? (
                  <>
                    <MessageSquare className="w-5 h-5" />
                    <span>Start asking</span>
                  </>
                ) : canAddSources ? (
                  <>
                    <Upload className="w-5 h-5" />
                    <span>Upload sources</span>
                  </>
                ) : (
                  <span>Ask an editor to add sources</span>
                )}
              </button>

              {currentProject && (
                <div
                  data-layout="welcome-actions"
                  className="grid text-left"
                  style={welcomeHeroStyles.actions}
                >
                  {/* These two looked clickable and did nothing; they are now
                      the two things a reader actually does from here. */}
                  <button
                    type="button"
                    onClick={canAddSources ? handleRequestAddSources : undefined}
                    disabled={!canAddSources}
                    className="text-left bg-[var(--card)] rounded-lg border border-[var(--border)] hover:border-[var(--input)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] transition-base"
                    style={welcomeHeroStyles.card}
                  >
                    <span className="block font-medium text-sm mb-1">Add more sources</span>
                    <span className="block text-sm text-[var(--muted-foreground)]">
                      {canAddSources
                        ? 'Files, web pages, YouTube videos or pasted text'
                        : 'Ask an owner or editor to add sources'}
                    </span>
                  </button>
                  {canEditProject && (
                  <button
                    type="button"
                    onClick={() => setShowChatSettings(true)}
                    className="text-left bg-[var(--card)] rounded-lg border border-[var(--border)] hover:border-[var(--input)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] transition-base"
                    style={welcomeHeroStyles.card}
                  >
                    <span className="block font-medium text-sm mb-1">Choose how answers read</span>
                    <span className="block text-sm text-[var(--muted-foreground)]">
                      Role and length; every answer still cites its sources
                    </span>
                  </button>
                  )}
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

              {/* While a question is pending the last message is the user's, so
                  a follow-up cannot be clicked mid-request. */}
              {lastMessage?.role === 'assistant' && currentConversation
                && currentConversation.id === followUpConversationId && (
                <FollowUpQuestions
                  conversationId={currentConversation.id}
                  messageId={lastMessage.id}
                  disabled={noSourcesSelected}
                  onAsk={(question) => void submitQuery(question)}
                />
              )}

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
                    className="text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current"
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
        className={`bg-[var(--background)] ${currentProject ? 'p-4' : 'p-3'}`}
      >
        <div className="max-w-3xl mx-auto">
          <div className={`min-w-0 flex items-end ${currentProject ? 'gap-3' : 'gap-2'}`}>
            {currentProject && canAddSources && (
              <button
                onClick={handleRequestAddSources}
                aria-label={'Attach file'}
                title={'Attach file'}
                className="flex-shrink-0 p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-lg transition-base"
              >
                <Paperclip className="w-5 h-5" />
              </button>
            )}
            {currentProject && canEditProject && (
              <button
                type="button"
                onClick={() => setShowChatSettings(true)}
                aria-label={'Chat settings'}
                title={'Chat settings'}
                className="flex-shrink-0 p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-lg transition-base"
              >
                <SlidersHorizontal className="w-5 h-5" />
              </button>
            )}
            
            <div className="min-w-0 flex-1 relative">
              <textarea
                ref={composerRef}
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
                    : !canChat
                      ? canAddSources ? 'Add sources to start chatting' : 'Waiting for a project source'
                      : noSourcesSelected
                        ? 'Select a source to start chatting'
                        : 'Ask anything about your sources...'
                }
                className={`w-full px-4 py-3 ${inputValue && hasDocuments ? 'pr-20' : ''} min-h-[4.5rem] sm:min-h-[2.75rem] max-h-40 overflow-y-hidden bg-[var(--card)] border border-[var(--input)] rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base text-sm`}
                rows={1}
                disabled={!canChat || isStreaming}
              />
              
              {inputValue && hasDocuments && (
                <span className="absolute right-3 bottom-2 text-xs text-[var(--muted-foreground)]">
                  {selectedSourceCount} {selectedSourceCount === 1 ? 'source' : 'sources'}
                </span>
              )}
            </div>
            
            <button
              onClick={handleSend}
              aria-label={'Send message'}
              title={'Send message'}
              disabled={!inputValue.trim() || !canChat || isStreaming || noSourcesSelected}
              className={`flex-shrink-0 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-base ${currentProject ? 'p-3' : 'p-2.5'}`}>
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
              className="mt-3 flex items-center gap-1 text-xs text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current">
              <span>New Conversation</span>
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {showChatSettings && currentProject && canEditProject && (
        <ChatSettingsDialog
          projectId={currentProject.id}
          onClose={() => setShowChatSettings(false)}
          onOutputLanguageChanged={onOutputLanguageChanged}
        />
      )}
    </div>
  );
}
