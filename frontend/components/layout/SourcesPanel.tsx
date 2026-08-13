"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { 
  Plus, 
  Search,
  FileText,
  Globe,
  Youtube,
  File as FileIcon,
  X,
  Loader2,
  FolderOpen,
  Eye,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import FileUpload from '../FileUpload';
import DocumentPreview from '../DocumentPreview';
import { useProjectDialog } from '../ProjectDialogProvider';
import useStore from '@/store/useStore';
import { Document } from '@/lib/api';
import {
  closeAddSourcesAfterSuccessfulUpload,
  requestAddSources,
} from '../sourceActions';
import useDialogFocus from '@/hooks/useDialogFocus';

interface SourcesPanelProps {
  isAddSourcesOpen: boolean;
  onAddSourcesOpenChange: (isOpen: boolean) => void;
  isCollapsed?: boolean;
  onCollapsedChange?: (isCollapsed: boolean) => void;
}

export default function SourcesPanel({
  isAddSourcesOpen,
  onAddSourcesOpenChange,
  isCollapsed = false,
  onCollapsedChange,
}: SourcesPanelProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [previewDocument, setPreviewDocument] = useState<Document | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [modalSession, setModalSession] = useState(0);
  const uploadCloseRef = useRef<HTMLButtonElement>(null);
  const uploadDialogRef = useRef<HTMLDivElement>(null);
  const uploadTitleId = useId();
  const isAddSourcesOpenRef = useRef(isAddSourcesOpen);
  const modalSessionRef = useRef(0);
  const wasAddSourcesOpenRef = useRef(false);

  isAddSourcesOpenRef.current = isAddSourcesOpen;

  // The dialog's open state lives in the page (so the chat CTA and paperclip can
  // open it), while the shared focus hook owns initial focus, Tab trapping,
  // Escape and focus restoration.
  const closeAddSources = useCallback(() => {
    if (!isUploading) {
      onAddSourcesOpenChange(false);
    }
  }, [isUploading, onAddSourcesOpenChange]);

  useDialogFocus({
    isOpen: isAddSourcesOpen,
    onClose: closeAddSources,
    dismissible: !isUploading,
    dialogRef: uploadDialogRef,
    initialFocusRef: uploadCloseRef,
  });

  const {
    projects,
    currentProject,
    documents,
    loadingDocuments,
    fetchProjects,
    selectProject,
    uploadDocument,
    createDocument,
    deleteDocument,
  } = useStore();
  const { openProjectDialog } = useProjectDialog();

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // Session counter so a stale upload can never close a dialog reopened after it.
  useEffect(() => {
    if (isAddSourcesOpen && !wasAddSourcesOpenRef.current) {
      const nextSession = modalSessionRef.current + 1;
      modalSessionRef.current = nextSession;
      setModalSession(nextSession);
    }

    if (!isAddSourcesOpen && wasAddSourcesOpenRef.current) {
      setIsUploading(false);
    }

    wasAddSourcesOpenRef.current = isAddSourcesOpen;
  }, [isAddSourcesOpen]);

  const handleUpload = async (items: File[] | string[]) => {
    if (!currentProject) {
      alert('Please select or create a project first');
      return;
    }

    const projectId = currentProject.id;
    const uploadSession = modalSession;
    await closeAddSourcesAfterSuccessfulUpload(async () => {
      for (const item of items) {
        if (item instanceof File) {
          await uploadDocument(projectId, item);
        } else {
          // Handle URL or YouTube link
          const isYouTube = item.includes('youtube.com') || item.includes('youtu.be');
          await createDocument(projectId, {
            name: item,
            type: isYouTube ? 'youtube' : 'url',
            url: item,
          });
        }
      }
    }, () => {
      if (
        modalSessionRef.current === uploadSession
        && isAddSourcesOpenRef.current
      ) {
        onAddSourcesOpenChange(false);
      }
    });
  };

  const handleUploadingChange = (uploadSession: number) => (uploading: boolean) => {
    if (
      modalSessionRef.current === uploadSession
      && isAddSourcesOpenRef.current
    ) {
      setIsUploading(uploading);
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!currentProject) return;
    
    if (confirm('Are you sure you want to delete this document?')) {
      try {
        await deleteDocument(currentProject.id, docId);
      } catch (error) {
        console.error('Failed to delete document:', error);
        alert('Failed to delete document');
      }
    }
  };

  const getSourceIcon = (type: string) => {
    switch (type) {
      case 'pdf':
      case 'text':
        return <FileText className="w-4 h-4" />;
      case 'url':
        return <Globe className="w-4 h-4" />;
      case 'youtube':
        return <Youtube className="w-4 h-4" />;
      default:
        return <FileIcon className="w-4 h-4" />;
    }
  };

  // Filter documents based on search query
  const filteredDocuments = documents.filter(doc => 
    doc.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <aside
      aria-label="來源"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-r border-[var(--border)] bg-[var(--sidebar-bg)] flex flex-col h-full"
    >
      <button
        type="button"
        onClick={() => onCollapsedChange?.(!isCollapsed)}
        aria-controls="sources-panel-content"
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? '展開來源' : '收合來源'}
        title={isCollapsed ? '展開來源' : '收合來源'}
        className="absolute top-2 right-2 z-10 p-1.5 hover:bg-[var(--card)] rounded-lg transition-base"
      >
        {isCollapsed ? (
          <PanelLeftOpen className="w-4 h-4" />
        ) : (
          <PanelLeftClose className="w-4 h-4" />
        )}
      </button>

      <div
        id="sources-panel-content"
        role="region"
        aria-label="來源面板內容"
        hidden={isCollapsed}
        className="min-h-0 flex-1 flex flex-col"
      >
      {/* Header */}
      <div className="p-4 border-b border-[var(--sidebar-border)]">
        <h2 className="pr-10 text-base font-medium mb-3">來源</h2>
        
        {/* Project Selector */}
        <div className="space-y-2 mb-3">
          <select
            aria-label={'選擇專案'}
            value={currentProject?.id || ''}
            onChange={(e) => {
              const project = projects.find(p => p.id === e.target.value);
              if (project) selectProject(project);
            }}
            className="w-full px-3 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
          >
            <option value="">Select a project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          
          <button
            onClick={openProjectDialog}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 border border-[var(--border)] rounded-lg hover:bg-[var(--card)] transition-base disabled:opacity-50"
          >
            <FolderOpen className="w-4 h-4" />
            <span className="text-sm">新增專案</span>
          </button>
        </div>
        
        {/* Add Source Button */}
        {currentProject && (
          <button 
            onClick={() => requestAddSources(Boolean(currentProject), onAddSourcesOpenChange)}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base"
          >
            <Plus className="w-4 h-4" />
            <span className="text-sm">新增來源</span>
          </button>
        )}

        {/* Search */}
        {currentProject && documents.length > 0 && (
          <div className="mt-3 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
            <input
              type="text"
              aria-label="搜尋來源"
              placeholder="搜尋來源"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
            />
          </div>
        )}
      </div>

      {/* Sources List */}
      <div className="flex-1 overflow-y-auto p-4">
        {!currentProject ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
              <FolderOpen className="w-8 h-8 text-[var(--muted-foreground)]" />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              請選擇或建立專案以開始使用
            </p>
          </div>
        ) : loadingDocuments ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : filteredDocuments.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
              <FileText className="w-8 h-8 text-[var(--muted-foreground)]" />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              {searchQuery ? '找不到來源' : '尚無來源'}
            </p>
            {!searchQuery && (
              <p className="text-xs text-[var(--muted-foreground)] mt-2">
                點選「新增來源」以上傳 PDF、網址或 YouTube 影片
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredDocuments.map((doc) => (
              <div
                key={doc.id}
                className="p-3 bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer group"
                onClick={() => setPreviewDocument(doc)}
              >
                <div className="flex items-start gap-3">
                  <div className="p-2 bg-[var(--muted)] rounded">
                    {getSourceIcon(doc.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium truncate">
                      {doc.name}
                    </h3>
                    <p className="text-xs text-[var(--muted-foreground)] mt-1">
                      {doc.status === 'processing' ? 'Processing...' : 
                       doc.status === 'ready' ? 'Ready' : doc.status}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreviewDocument(doc);
                      }}
                      className="p-1 hover:bg-[var(--muted)] rounded"
                      aria-label={'\u9810\u89bd\u6587\u4ef6'}
                      title={'\u9810\u89bd\u6587\u4ef6'}
                    >
                      <Eye className="w-3 h-3" />
                    </button>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteDocument(doc.id);
                      }}
                      className="p-1 hover:bg-[var(--muted)] rounded"
                      aria-label={'\u522a\u9664\u6587\u4ef6'}
                      title={'\u522a\u9664\u6587\u4ef6'}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      </div>

      {/* Upload Modal */}
      {isAddSourcesOpen && currentProject && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div
            ref={uploadDialogRef}
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby={uploadTitleId}
            aria-busy={isUploading}
            className="bg-[var(--background)] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto"
          >
            <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
              <h3 id={uploadTitleId} className="text-lg font-semibold">新增來源</h3>
              <button
                ref={uploadCloseRef}
                onClick={closeAddSources}
                type="button"
                aria-label={'\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846'}
                title={'\u95dc\u9589\u65b0\u589e\u4f86\u6e90\u5c0d\u8a71\u6846'}
                disabled={isUploading}
                className="p-1 hover:bg-[var(--muted)] rounded transition-base"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <FileUpload
              onUpload={handleUpload}
              onUploadingChange={handleUploadingChange(modalSession)}
            />
          </div>
        </div>
      )}

      {/* Document Preview Modal */}
      {previewDocument && (
        <DocumentPreview
          document={previewDocument}
          onClose={() => setPreviewDocument(null)}
        />
      )}
    </aside>
  );
}
