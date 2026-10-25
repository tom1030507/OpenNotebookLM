'use client';

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { 
  X, 
  Download, 
  ExternalLink, 
  FileText, 
  FileSpreadsheet,
  Presentation,
  BookOpen,
  Globe, 
  Youtube,
  Maximize2,
  Minimize2,
  Copy,
  Check
} from 'lucide-react';
import api, { Citation, Document, SourceGuide } from '@/lib/api';
import useDialogFocus from '@/hooks/useDialogFocus';
import usePreviewSource from '@/hooks/usePreviewSource';
import useStore from '@/store/useStore';

interface DocumentPreviewProps {
  document: Document;
  citation?: Citation;
  onClose: () => void;
}

type ContentRequest =
  | { documentId: string; status: 'loading' }
  | { documentId: string; status: 'loaded'; content: string }
  | { documentId: string; status: 'error'; message: string };

type GuideRequest =
  | { documentId: string; status: 'loading' }
  | { documentId: string; status: 'loaded'; guide: SourceGuide }
  | { documentId: string; status: 'error'; message: string };

const EXTRACTED_TEXT_TYPES: Document['type'][] = [
  'docx', 'pptx', 'xlsx', 'epub', 'txt', 'md',
  'mp3', 'm4a', 'wav', 'ogg', 'webm', 'flac', 'url',
];

export default function DocumentPreview({ document, citation, onClose }: DocumentPreviewProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [contentRequest, setContentRequest] = useState<ContentRequest | null>(null);
  const [guideRequest, setGuideRequest] = useState<GuideRequest | null>(null);
  const [contentRefreshCount, setContentRefreshCount] = useState(0);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const citationMarkRef = useRef<HTMLElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const titleId = useId();
  // An uploaded file is behind the API's protected route, so its bytes arrive
  // as an object URL rather than as an address the browser can load directly.
  const preview = usePreviewSource(document);
  const shouldFetchContent =
    EXTRACTED_TEXT_TYPES.includes(document.type) && document.content === undefined;
  const shouldRequestContent = shouldFetchContent && (
    document.status === 'ready' || contentRefreshCount > 0
  );
  const currentContentRequest = contentRequest?.documentId === document.id
    ? contentRequest
    : null;
  const currentGuideRequest = guideRequest?.documentId === document.id
    ? guideRequest
    : null;
  const guide = currentGuideRequest?.status === 'loaded'
    ? currentGuideRequest.guide
    : undefined;
  const fetchedContent = currentContentRequest?.status === 'loaded'
    ? currentContentRequest.content
    : undefined;
  const content = document.content ?? (
    fetchedContent !== undefined && (document.status === 'ready' || fetchedContent.length > 0)
      ? fetchedContent
      : undefined
  );
  const contentLoading = shouldRequestContent && (
    currentContentRequest === null || currentContentRequest.status === 'loading'
  );
  const contentError = currentContentRequest?.status === 'error'
    ? currentContentRequest.message
    : shouldFetchContent && document.status === 'error'
      ? document.error_message || 'Source processing failed.'
      : undefined;
  const contentWaiting = shouldFetchContent
    && document.status !== 'ready'
    && document.status !== 'error'
    && !contentLoading
    && !contentError;
  const guideLoading = document.status === 'ready' && (
    currentGuideRequest === null || currentGuideRequest.status === 'loading'
  );
  const guideError = currentGuideRequest?.status === 'error'
    ? currentGuideRequest.message
    : undefined;
  const citationRange = useCallback((text: string) => {
    const start = citation?.start_offset;
    const end = citation?.end_offset;
    if (
      typeof start !== 'number'
      || typeof end !== 'number'
      || !Number.isSafeInteger(start)
      || !Number.isSafeInteger(end)
      || start < 0
      || start >= text.length
      || end <= start
    ) return null;
    return { start, end: Math.min(end, text.length) };
  }, [citation?.end_offset, citation?.start_offset]);
  const renderHighlightedText = (text: string) => {
    const range = citationRange(text);
    if (!range) return text;
    return <>
      {text.slice(0, range.start)}
      <mark ref={citationMarkRef}>{text.slice(range.start, range.end)}</mark>
      {text.slice(range.end)}
    </>;
  };

  useEffect(() => {
    if (!shouldRequestContent) {
      return;
    }

    let cancelled = false;
    setContentRequest({ documentId: document.id, status: 'loading' });
    api.fetchDocumentContent(document.id)
      .then((extractedContent) => {
        if (!cancelled) {
          setContentRequest({
            documentId: document.id,
            status: 'loaded',
            content: extractedContent,
          });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setContentRequest({
            documentId: document.id,
            status: 'error',
            message: error instanceof Error ? error.message : 'Could not load extracted text.',
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    contentRefreshCount,
    document.content,
    document.id,
    document.status,
    shouldRequestContent,
  ]);

  useEffect(() => {
    if (content === undefined || !citationRange(content)) return;
    citationMarkRef.current?.scrollIntoView?.({ block: 'center' });
  }, [citationRange, content]);

  useEffect(() => {
    const audio = audioRef.current;
    const timestamp = citation?.timestamp;
    if (!audio || typeof timestamp !== 'number' || !Number.isFinite(timestamp)) return;
    const seek = () => { audio.currentTime = Math.max(0, timestamp); };
    if (audio.readyState >= 1) {
      seek();
      return;
    }
    audio.addEventListener('loadedmetadata', seek, { once: true });
    return () => audio.removeEventListener('loadedmetadata', seek);
  }, [citation?.timestamp, document.id, preview.src]);

  useEffect(() => {
    if (document.status !== 'ready') {
      return;
    }

    let cancelled = false;
    setGuideRequest({ documentId: document.id, status: 'loading' });
    api.fetchDocumentGuide(document.id)
      .then((loadedGuide) => {
        if (!cancelled) {
          setGuideRequest({ documentId: document.id, status: 'loaded', guide: loadedGuide });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setGuideRequest({
            documentId: document.id,
            status: 'error',
            message: error instanceof Error ? error.message : 'Could not load source guide.',
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [document.id, document.status]);

  useDialogFocus({
    isOpen: true,
    onClose,
    dialogRef,
    initialFocusRef: closeButtonRef,
  });

  const handleCopy = async () => {
    if (content !== undefined) {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = () => {
    // Create a download link for the document content
    const blob = new Blob([content || ''], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = window.document.createElement('a');
    a.href = url;
    a.download = `${document.name}.txt`;
    window.document.body.appendChild(a);
    a.click();
    window.document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleOpenExternal = () => {
    // For an upload this is the object URL, which a new tab can open; the
    // protected route behind it would answer that tab with a 401.
    const target = preview.src || document.url;

    if (target) {
      window.open(target, '_blank');
    }
  };

  const handleAskAboutTopic = (topic: string) => {
    const state = useStore.getState();
    const projectId = state.currentProject?.id;
    const source = state.documents.find((item) => item.id === document.id);
    if (!projectId || document.status !== 'ready' || source?.status !== 'ready') {
      return;
    }

    state.setAllSourcesSelected(projectId, false);
    state.toggleSourceSelected(projectId, document.id);
    state.draftMindMapQuestion(
      projectId,
      `What does this source say about ${topic}?`,
    );
    onClose();
  };

  const renderGuide = () => {
    if (guide) {
      return (
        <section
          aria-label="Source guide"
          className="shrink-0 max-h-56 overflow-y-auto p-5 border-b border-[var(--border)] bg-[var(--card)]"
        >
          <h4 className="text-sm font-semibold">Summary</h4>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">{guide.summary}</p>
          {guide.topics.length > 0 && (
            <div className="mt-3">
              <h4 className="text-sm font-semibold">Key topics</h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {guide.topics.map((topic) => (
                  <button
                    key={topic}
                    type="button"
                    onClick={() => handleAskAboutTopic(topic)}
                    className="rounded-full border border-[var(--border)] px-3 py-1 text-xs hover:bg-[var(--muted)]"
                  >
                    {topic}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      );
    }
    if (guideLoading) {
      return (
        <div className="shrink-0 px-5 py-3 text-sm text-[var(--muted-foreground)]" role="status">
          Loading source guide...
        </div>
      );
    }
    if (guideError) {
      return (
        <div className="shrink-0 px-5 py-3 text-sm text-[var(--muted-foreground)]" role="alert">
          {guideError}
        </div>
      );
    }
    return null;
  };

  const getIcon = () => {
    switch (document.type) {
      case 'pdf':
      case 'text':
      case 'txt':
      case 'md':
      case 'docx':
        return <FileText className="w-5 h-5" />;
      case 'pptx':
        return <Presentation className="w-5 h-5" />;
      case 'xlsx':
        return <FileSpreadsheet className="w-5 h-5" />;
      case 'epub':
        return <BookOpen className="w-5 h-5" />;
      case 'url':
        return <Globe className="w-5 h-5" />;
      case 'youtube':
        return <Youtube className="w-5 h-5" />;
      default:
        return <FileText className="w-5 h-5" />;
    }
  };

  const renderExtractedContent = () => {
    if (content !== undefined) {
      return (
        <div className="p-6 overflow-y-auto h-full">
          <pre className="whitespace-pre-wrap text-sm font-mono">
            {renderHighlightedText(content)}
          </pre>
        </div>
      );
    }
    if (contentLoading) {
      return (
        <div className="p-8 text-center" role="status">
          <p className="text-[var(--muted-foreground)]">
            Loading extracted text...
          </p>
        </div>
      );
    }
    if (contentWaiting) {
      return (
        <div className="p-8 text-center">
          <p className="text-[var(--muted-foreground)]" role="status">
            Source is still processing.
          </p>
          <button
            type="button"
            className="mt-3 text-sm text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current"
            onClick={() => setContentRefreshCount((count) => count + 1)}
          >
            Check for extracted text
          </button>
        </div>
      );
    }
    if (contentError) {
      return (
        <div className="p-8 text-center">
          <p className="text-[var(--muted-foreground)]" role="alert">
            {contentError}
          </p>
        </div>
      );
    }
    return (
      <div className="p-8 text-center">
        <p className="text-[var(--muted-foreground)]">
          Content preview not available
        </p>
      </div>
    );
  };

  const renderContent = () => {
    switch (document.type) {
      case 'pdf':
        if (preview.src) {
          return (
            <div className="h-full min-h-0 flex flex-col">
              {(citation?.page != null || citation?.text) && (
                <div className="shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm">
                  {citation?.page != null && (
                    <p className="text-xs text-[var(--muted-foreground)]">Page {citation.page}</p>
                  )}
                  {citation?.text && <p className="mt-1"><mark>{citation.text}</mark></p>}
                </div>
              )}
              <iframe
                src={citation?.page != null
                  ? `${preview.src}#page=${Math.max(1, Math.floor(citation.page))}`
                  : preview.src}
                className="w-full flex-1 min-h-0"
                title={document.name}
              />
            </div>
          );
        }
        if (document.url && !preview.error) {
          return (
            <div className="p-8 text-center">
              <p className="text-[var(--muted-foreground)]">
                Loading preview...
              </p>
            </div>
          );
        }
        return (
          <div className="p-8 text-center">
            <FileText className="w-16 h-16 mx-auto mb-4 text-[var(--muted-foreground)]" />
            <p className="text-[var(--muted-foreground)]">
              {preview.error || 'PDF preview not available'}
            </p>
            {content !== undefined && (
              <div className="mt-4 text-left max-w-3xl mx-auto">
                <h4 className="font-medium mb-2">Extracted Text:</h4>
                <pre className="whitespace-pre-wrap text-sm bg-[var(--muted)] p-4 rounded-lg">
                  {content}
                </pre>
              </div>
            )}
          </div>
        );

      case 'url':
        return (
          <div className="h-full flex flex-col">
            {document.url && (
              <div className="p-4 bg-[var(--card)] border-b border-[var(--border)] flex items-center gap-2">
                <Globe className="w-4 h-4 text-[var(--muted-foreground)]" />
                <a
                  href={document.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current truncate"
                >
                  {document.url}
                </a>
              </div>
            )}
            <div className="flex-1 min-h-0">
              {renderExtractedContent()}
            </div>
          </div>
        );

      case 'youtube':
        if (document.url) {
          // Extract YouTube video ID
          const videoId = document.url.match(
            /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)/
          )?.[1];

          if (videoId) {
            const embedUrl = new URL(`https://www.youtube.com/embed/${videoId}`);
            if (
              typeof citation?.timestamp === 'number'
              && Number.isFinite(citation.timestamp)
            ) {
              embedUrl.searchParams.set(
                'start',
                String(Math.max(0, Math.floor(citation.timestamp))),
              );
            }
            return (
              <div className="h-full flex flex-col">
                <div className="p-4 bg-[var(--card)] border-b border-[var(--border)] flex items-center gap-2">
                  <Youtube className="w-4 h-4 text-[var(--error)]" />
                  <a
                    href={document.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current truncate"
                  >
                    {document.name}
                  </a>
                </div>
                <div className="flex-1 bg-black flex items-center justify-center">
                  <iframe
                    src={embedUrl.toString()}
                    className="w-full max-w-4xl aspect-video"
                    title={document.name}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
                {document.content && (
                  <div className="p-4 bg-[var(--card)] border-t border-[var(--border)]">
                    <h4 className="font-medium mb-2 text-sm">Transcript:</h4>
                    <pre className="whitespace-pre-wrap text-xs text-[var(--muted-foreground)] max-h-32 overflow-y-auto">
                      {renderHighlightedText(document.content)}
                    </pre>
                  </div>
                )}
              </div>
            );
          }
        }
        break;

      case 'mp3':
      case 'm4a':
      case 'wav':
      case 'ogg':
      case 'webm':
      case 'flac':
        return (
          <div className="h-full min-h-0 flex flex-col gap-3 p-4">
            {preview.src ? (
              <audio ref={audioRef} src={preview.src} controls preload="metadata" className="w-full shrink-0" />
            ) : (
              <p className="shrink-0 text-sm text-[var(--muted-foreground)]" role={preview.error ? 'alert' : 'status'}>
                {preview.error || 'Loading audio preview...'}
              </p>
            )}
            <div className="min-h-0 flex-1">
              {renderExtractedContent()}
            </div>
          </div>
        );

      case 'text':
      case 'docx':
      case 'pptx':
      case 'xlsx':
      case 'epub':
      case 'txt':
      case 'md':
      default:
        return renderExtractedContent();
    }

    return (
      <div className="p-8 text-center">
        <p className="text-[var(--muted-foreground)]">
          Content preview not available
        </p>
      </div>
    );
  };

  return (
    <div 
      // The backdrop always covers the window; only the panel insets. An inset
      // backdrop left a strip of the live workspace showing around the edge.
      className={`fixed inset-0 bg-[var(--overlay)] flex items-center justify-center z-50 ${
        isFullscreen ? '' : 'p-4'
      }`}
    >
      <div 
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className={`bg-[var(--popover)] border border-[var(--border)] shadow-xl rounded-lg flex flex-col ${
          isFullscreen ? 'w-full h-full' : 'w-full max-w-5xl h-[90vh]'
        }`}
      >
        {/* Header */}
        <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="shrink-0 text-[var(--muted-foreground)] [&_svg]:h-4 [&_svg]:w-4">
              {getIcon()}
            </div>
            <div>
              <h3 id={titleId} className="font-medium">{document.name}</h3>
              <p className="text-xs text-[var(--muted-foreground)]">
                {document.type.toUpperCase()} • {document.status}
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            {content !== undefined && (
              <button
                onClick={handleCopy}
                aria-label={'Copy content'}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title={'Copy content'}
              >
                {copied ? (
                  <Check className="w-4 h-4 text-[var(--success)]" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            )}
            
            {document.url && (
              <button
                onClick={handleOpenExternal}
                aria-label={'Open in new tab'}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title={'Open in new tab'}
              >
                <ExternalLink className="w-4 h-4" />
              </button>
            )}
            
            {content !== undefined && (
              <button
                onClick={handleDownload}
                aria-label={'Download document'}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title={'Download document'}
              >
                <Download className="w-4 h-4" />
              </button>
            )}
            
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              aria-label={'Toggle fullscreen'}
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
              title={'Toggle fullscreen'}
            >
              {isFullscreen ? (
                <Minimize2 className="w-4 h-4" />
              ) : (
                <Maximize2 className="w-4 h-4" />
              )}
            </button>
            
            <button
              ref={closeButtonRef}
              onClick={onClose}
              type="button"
              aria-label={'Close document preview dialog'}
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
              title={'Close document preview dialog'}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {renderGuide()}
          <div className="min-h-0 flex-1 overflow-hidden">
            {renderContent()}
          </div>
        </div>

        {/* Footer */}
        {['processing', 'transcribing'].includes(document.status) && (
          <div className="p-4 border-t border-[var(--border)] bg-[var(--warning-bg)]">
            <p className="text-sm text-[var(--warning)]">
              This document is still being processed. Some features may not be available yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
