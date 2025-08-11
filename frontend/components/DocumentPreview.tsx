'use client';

import React, { useState } from 'react';
import { 
  X, 
  Download, 
  ExternalLink, 
  FileText, 
  Globe, 
  Youtube,
  Maximize2,
  Minimize2,
  Copy,
  Check
} from 'lucide-react';
import { Document } from '@/lib/api';

interface DocumentPreviewProps {
  document: Document;
  onClose: () => void;
}

export default function DocumentPreview({ document, onClose }: DocumentPreviewProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (document.content) {
      await navigator.clipboard.writeText(document.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = () => {
    // Create a download link for the document content
    const blob = new Blob([document.content || ''], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${document.name}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleOpenExternal = () => {
    if (document.url) {
      window.open(document.url, '_blank');
    }
  };

  const getIcon = () => {
    switch (document.type) {
      case 'pdf':
      case 'text':
        return <FileText className="w-5 h-5" />;
      case 'url':
        return <Globe className="w-5 h-5" />;
      case 'youtube':
        return <Youtube className="w-5 h-5" />;
      default:
        return <FileText className="w-5 h-5" />;
    }
  };

  const renderContent = () => {
    switch (document.type) {
      case 'pdf':
        if (document.url) {
          return (
            <iframe
              src={document.url}
              className="w-full h-full"
              title={document.name}
            />
          );
        }
        return (
          <div className="p-8 text-center">
            <FileText className="w-16 h-16 mx-auto mb-4 text-[var(--muted-foreground)]" />
            <p className="text-[var(--muted-foreground)]">
              PDF preview not available
            </p>
            {document.content && (
              <div className="mt-4 text-left max-w-3xl mx-auto">
                <h4 className="font-medium mb-2">Extracted Text:</h4>
                <pre className="whitespace-pre-wrap text-sm bg-[var(--muted)] p-4 rounded-lg">
                  {document.content}
                </pre>
              </div>
            )}
          </div>
        );

      case 'url':
        if (document.url) {
          return (
            <div className="h-full flex flex-col">
              <div className="p-4 bg-[var(--card)] border-b border-[var(--border)] flex items-center gap-2">
                <Globe className="w-4 h-4 text-[var(--muted-foreground)]" />
                <a
                  href={document.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-[var(--primary)] hover:underline truncate"
                >
                  {document.url}
                </a>
              </div>
              <iframe
                src={document.url}
                className="flex-1 w-full"
                title={document.name}
                sandbox="allow-same-origin allow-scripts"
              />
            </div>
          );
        }
        break;

      case 'youtube':
        if (document.url) {
          // Extract YouTube video ID
          const videoId = document.url.match(
            /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)/
          )?.[1];

          if (videoId) {
            return (
              <div className="h-full flex flex-col">
                <div className="p-4 bg-[var(--card)] border-b border-[var(--border)] flex items-center gap-2">
                  <Youtube className="w-4 h-4 text-red-600" />
                  <a
                    href={document.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-[var(--primary)] hover:underline truncate"
                  >
                    {document.name}
                  </a>
                </div>
                <div className="flex-1 bg-black flex items-center justify-center">
                  <iframe
                    src={`https://www.youtube.com/embed/${videoId}`}
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
                      {document.content}
                    </pre>
                  </div>
                )}
              </div>
            );
          }
        }
        break;

      case 'text':
      default:
        if (document.content) {
          return (
            <div className="p-6 overflow-y-auto h-full">
              <pre className="whitespace-pre-wrap text-sm font-mono">
                {document.content}
              </pre>
            </div>
          );
        }
        break;
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
      className={`fixed bg-black bg-opacity-50 flex items-center justify-center z-50 ${
        isFullscreen ? 'inset-0' : 'inset-4'
      }`}
    >
      <div 
        className={`bg-[var(--background)] rounded-lg flex flex-col ${
          isFullscreen ? 'w-full h-full' : 'w-full max-w-5xl h-[90vh]'
        }`}
      >
        {/* Header */}
        <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[var(--muted)] rounded">
              {getIcon()}
            </div>
            <div>
              <h3 className="font-medium">{document.name}</h3>
              <p className="text-xs text-[var(--muted-foreground)]">
                {document.type.toUpperCase()} • {document.status}
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            {document.content && (
              <button
                onClick={handleCopy}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title="Copy content"
              >
                {copied ? (
                  <Check className="w-4 h-4 text-green-600" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            )}
            
            {document.url && (
              <button
                onClick={handleOpenExternal}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title="Open in new tab"
              >
                <ExternalLink className="w-4 h-4" />
              </button>
            )}
            
            {document.content && (
              <button
                onClick={handleDownload}
                className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
                title="Download"
              >
                <Download className="w-4 h-4" />
              </button>
            )}
            
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            >
              {isFullscreen ? (
                <Minimize2 className="w-4 h-4" />
              ) : (
                <Maximize2 className="w-4 h-4" />
              )}
            </button>
            
            <button
              onClick={onClose}
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {renderContent()}
        </div>

        {/* Footer */}
        {document.status === 'processing' && (
          <div className="p-4 border-t border-[var(--border)] bg-yellow-50 dark:bg-yellow-900/20">
            <p className="text-sm text-yellow-800 dark:text-yellow-200">
              This document is still being processed. Some features may not be available yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
