"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { 
  Plus, 
  Search,
  FileText,
  FileSpreadsheet,
  Globe,
  BookOpen,
  Presentation,
  Youtube,
  File as FileIcon,
  X,
  Loader2,
  FolderOpen,
  Eye,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
} from 'lucide-react';
import FileUpload from '../FileUpload';
import DocumentPreview from '../DocumentPreview';
import { useProjectDialog } from '../ProjectDialogProvider';
import useStore from '@/store/useStore';
import { Document, DocumentStatus } from '@/lib/api';
import {
  closeAddSourcesAfterSuccessfulUpload,
  requestAddSources,
} from '../sourceActions';
import useDialogFocus from '@/hooks/useDialogFocus';

// A source is only "Ready" once the backend can retrieve it, so the states
// before that need names a reader recognises rather than the raw status word.
const STATUS_LABELS: Partial<Record<DocumentStatus, string>> = {
  queued: 'Queued',
  processing: 'Processing...',
  transcribing: 'Transcribing...',
  ready: 'Ready',
  error: 'Failed',
};

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
    renameDocument,
    deselectedSources,
    toggleSourceSelected,
    setAllSourcesSelected,
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

  const handleAddText = async (title: string, content: string) => {
    if (!currentProject) return;

    const projectId = currentProject.id;
    const uploadSession = modalSession;
    await closeAddSourcesAfterSuccessfulUpload(
      () => createDocument(projectId, { name: title, type: 'text', content }),
      () => {
        if (
          modalSessionRef.current === uploadSession
          && isAddSourcesOpenRef.current
        ) {
          onAddSourcesOpenChange(false);
        }
      },
    );
  };

  const handleRenameDocument = async (doc: Document) => {
    const title = prompt('Rename source', doc.name)?.trim();
    if (!title || title === doc.name) return;

    try {
      await renameDocument(doc.id, title);
    } catch (error) {
      console.error('Failed to rename document:', error);
      alert('Failed to rename document');
    }
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
      case 'txt':
      case 'md':
      case 'docx':
        return <FileText className="w-4 h-4" />;
      case 'epub':
        return <BookOpen className="w-4 h-4" />;
      case 'pptx':
        return <Presentation className="w-4 h-4" />;
      case 'xlsx':
        return <FileSpreadsheet className="w-4 h-4" />;
      case 'url':
        return <Globe className="w-4 h-4" />;
      case 'youtube':
        return <Youtube className="w-4 h-4" />;
      default:
        return <FileIcon className="w-4 h-4" />;
    }
  };

  const deselected = (currentProject && deselectedSources[currentProject.id]) || [];
  const selectedCount = documents.filter((doc) => !deselected.includes(doc.id)).length;
  const allSelected = selectedCount === documents.length;

  // Filter documents based on search query
  const filteredDocuments = documents.filter(doc => 
    doc.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <aside
      aria-label="Sources"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-r border-[var(--border)] bg-[var(--sidebar-bg)] flex flex-col h-full"
    >
      <button
        type="button"
        onClick={() => onCollapsedChange?.(!isCollapsed)}
        aria-controls="sources-panel-content"
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? 'Expand Sources' : 'Collapse Sources'}
        title={isCollapsed ? 'Expand Sources' : 'Collapse Sources'}
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
        aria-label="Sources panel content"
        hidden={isCollapsed}
        className="min-h-0 flex-1 flex flex-col"
      >
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-[var(--sidebar-border)]">
        <h2 className="pr-10 text-sm font-semibold mb-3">Sources</h2>
        
        {/* Project selector and New Project share one row: stacked, the two
            took 90px of a column that also has to hold the source list. */}
        <div className="flex items-center gap-2 mb-2">
          <select
            aria-label={'Select a project'}
            value={currentProject?.id || ''}
            onChange={(e) => {
              const project = projects.find(p => p.id === e.target.value);
              if (project) selectProject(project);
            }}
            className="min-w-0 flex-1 h-9 px-2.5 bg-[var(--card)] border border-[var(--input)] rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
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
            aria-label="New Project"
            title="New Project"
            className="shrink-0 h-9 w-9 flex items-center justify-center border border-[var(--input)] bg-[var(--card)] rounded-md hover:bg-[var(--muted)] transition-base disabled:opacity-50"
          >
            <FolderOpen className="w-4 h-4" />
          </button>
        </div>
        
        {/* Add Source Button */}
        {currentProject && (
          <button 
            onClick={() => requestAddSources(Boolean(currentProject), onAddSourcesOpenChange)}
            className="w-full h-9 flex items-center justify-center gap-2 px-4 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md hover:bg-[var(--primary-hover)] transition-base"
          >
            <Plus className="w-4 h-4" />
            <span className="text-sm font-medium">Add Source</span>
          </button>
        )}

        {/* Search */}
        {currentProject && documents.length > 0 && (
          <div className="mt-2 relative">
            <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
            <input
              type="text"
              aria-label="Search sources"
              placeholder="Search sources"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-9 pl-9 pr-3 bg-[var(--card)] border border-[var(--input)] rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
            />
          </div>
        )}
      </div>

      {/* Sources List */}
      {currentProject && (
        <div className="flex-1 overflow-y-auto px-2 py-3">
          {loadingDocuments ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="text-center py-8">
              <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
                <FileText className="w-8 h-8 text-[var(--muted-foreground)]" />
              </div>
              <p className="text-sm text-[var(--muted-foreground)]">
                {searchQuery ? 'No sources found' : 'No sources yet'}
              </p>
              {!searchQuery && (
                <p className="text-xs text-[var(--muted-foreground)] mt-2">
                  Click &ldquo;Add Source&rdquo; to upload files, URLs, or YouTube videos
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-0.5">
              <label className="flex items-center gap-2 px-2 pb-2 text-xs text-[var(--muted-foreground)] cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(input) => {
                    if (input) input.indeterminate = selectedCount > 0 && !allSelected;
                  }}
                  onChange={() => setAllSourcesSelected(currentProject.id, !allSelected)}
                  className="h-4 w-4 accent-[var(--primary)]"
                />
                <span className="flex-1">Select all sources</span>
                <span>{selectedCount} of {documents.length} selected</span>
              </label>
              {filteredDocuments.map((doc) => (
                <div
                  key={doc.id}
                  // Rows, not bordered cards: a list of peers read as a stack of
                  // boxes, and each border cost the name a few characters.
                  className="relative px-2 py-2 rounded-md hover:bg-[var(--muted)] transition-base cursor-pointer group"
                  onClick={() => setPreviewDocument(doc)}
                >
                  <div className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={!deselected.includes(doc.id)}
                      onChange={() => toggleSourceSelected(currentProject.id, doc.id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Use ${doc.name} in answers and Studio`}
                      className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--primary)] cursor-pointer"
                    />
                    <span className="mt-0.5 shrink-0 text-[var(--muted-foreground)] [&_svg]:h-4 [&_svg]:w-4">
                      {getSourceIcon(doc.type)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-medium truncate" title={doc.name}>
                        {doc.name}
                      </h3>
                      <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                        {STATUS_LABELS[doc.status] ?? doc.status}
                      </p>
                      {doc.status === 'error' && doc.error_message && (
                        <p className="text-xs text-[var(--error)] mt-1 break-words">
                          {doc.error_message}
                        </p>
                      )}
                    </div>
                  </div>
                  {/* Out of flow on purpose. In the flex row this pair held 44px
                      of a 190px card even while invisible at opacity-0, which is
                      what cut a filename down to a handful of characters.
                      Overlaying it spends that width only while it is on screen,
                      and focus-within keeps it reachable by keyboard. */}
                  <div className="absolute right-1.5 top-1.5 flex items-center gap-0.5 rounded bg-[var(--muted)] pl-1 opacity-0 transition-colors group-hover:opacity-100 group-focus-within:opacity-100">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreviewDocument(doc);
                      }}
                      className="p-1 hover:bg-[var(--card)] rounded"
                      aria-label={'Preview document'}
                      title={'Preview document'}
                    >
                      <Eye className="w-3 h-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleRenameDocument(doc);
                      }}
                      className="p-1 hover:bg-[var(--card)] rounded"
                      aria-label={'Rename document'}
                      title={'Rename document'}
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteDocument(doc.id);
                      }}
                      className="p-1 hover:bg-[var(--card)] rounded"
                      aria-label={'Delete document'}
                      title={'Delete document'}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      </div>

      {/* Upload Modal */}
      {isAddSourcesOpen && currentProject && (
        <div className="fixed inset-0 bg-[var(--overlay)] flex items-center justify-center z-50">
          <div
            ref={uploadDialogRef}
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby={uploadTitleId}
            aria-busy={isUploading}
            className="bg-[var(--popover)] border border-[var(--border)] shadow-xl rounded-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto"
          >
            <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
              <h3 id={uploadTitleId} className="text-lg font-semibold">Add Source</h3>
              <button
                ref={uploadCloseRef}
                onClick={closeAddSources}
                type="button"
                aria-label={'Close add sources dialog'}
                title={'Close add sources dialog'}
                disabled={isUploading}
                className="p-1 hover:bg-[var(--muted)] rounded transition-base"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <FileUpload
              onUpload={handleUpload}
              onUploadingChange={handleUploadingChange(modalSession)}
              onAddText={handleAddText}
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
