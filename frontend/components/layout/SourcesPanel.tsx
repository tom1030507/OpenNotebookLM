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
  Copy,
  Loader2,
  FolderOpen,
  Eye,
  PanelLeftClose,
  PanelLeftOpen,
  ArrowRightLeft,
  Pencil,
  BarChart3,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import FileUpload from '../FileUpload';
import DocumentPreview from '../DocumentPreview';
import ProjectSearch from '../ProjectSearch';
import ProjectMergeDialog from '../ProjectMergeDialog';
import { useProjectDialog } from '../ProjectDialogProvider';
import useStore from '@/store/useStore';
import api, {
  Citation,
  Document,
  DocumentStatus,
  Project,
  ProjectMergeMode,
  ProjectSourceGroup,
} from '@/lib/api';
import {
  closeAddSourcesAfterSuccessfulUpload,
  requestAddSources,
} from '../sourceActions';
import useDialogFocus from '@/hooks/useDialogFocus';
import ProjectCover from '../ProjectCover';
import ProjectAnalyticsDialog from '../ProjectAnalyticsDialog';
import { findProjectCoverColor, projectCoverStyle } from '@/lib/projectCover';

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
  const [previewCitation, setPreviewCitation] = useState<Citation | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDuplicating, setIsDuplicating] = useState(false);
  const [isMergeDialogOpen, setIsMergeDialogOpen] = useState(false);
  const [mergeSourceProject, setMergeSourceProject] = useState<Project | null>(null);
  const [isDeletingProject, setIsDeletingProject] = useState(false);
  const [isAnalyticsOpen, setIsAnalyticsOpen] = useState(false);
  const [projectActionError, setProjectActionError] = useState('');
  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [tagSaving, setTagSaving] = useState(false);
  const [tagError, setTagError] = useState('');
  const [sourceGroupsState, setSourceGroupsState] = useState<{
    projectId: string;
    groups: ProjectSourceGroup[];
  } | null>(null);
  const [newSourceGroupName, setNewSourceGroupName] = useState('');
  const [sourceGroupSaving, setSourceGroupSaving] = useState(false);
  const [sourceGroupError, setSourceGroupError] = useState('');
  const [savingGroupDocumentId, setSavingGroupDocumentId] = useState<string | null>(null);
  const [watchedFolderEnabled, setWatchedFolderEnabled] = useState(false);
  const [watchedFolderPath, setWatchedFolderPath] = useState('');
  const [watchedFolderSaving, setWatchedFolderSaving] = useState(false);
  const [watchedFolderError, setWatchedFolderError] = useState('');
  const [resyncingDocumentId, setResyncingDocumentId] = useState<string | null>(null);
  const [pendingSearchPreview, setPendingSearchPreview] = useState<{
    projectId: string;
    documentId: string;
  } | null>(null);
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
    duplicateProject,
    mergeProject,
    deleteProject,
    updateProjectTags,
    uploadDocument,
    createDocument,
    deleteDocument,
    renameDocument,
    refreshDocuments,
    deselectedSources,
    toggleSourceSelected,
    setAllSourcesSelected,
    setSourcesSelected,
    citationPreview,
    clearCitationPreview,
  } = useStore();
  const { openProjectDialog } = useProjectDialog();
  const canManageProject = currentProject?.role === 'owner';
  const currentProjectId = currentProject?.id;
  const canManageSources = currentProject?.role === 'owner'
    || currentProject?.role === 'editor';
  const mergeTargets = projects.filter(
    (project) => project.id !== currentProjectId && project.role === 'owner',
  );
  const sourceGroups = sourceGroupsState && sourceGroupsState.projectId === currentProjectId
    ? sourceGroupsState.groups
    : [];

  useEffect(() => {
    let active = true;
    if (!currentProjectId) {
      setSourceGroupsState(null);
      return () => { active = false; };
    }
    setSourceGroupError('');
    api.getProjectSourceGroups(currentProjectId).then((groups) => {
      if (active) setSourceGroupsState({ projectId: currentProjectId, groups });
    }).catch((error) => {
      if (!active) return;
      setSourceGroupsState({ projectId: currentProjectId, groups: [] });
      setSourceGroupError(error instanceof Error ? error.message : 'Could not load source groups');
    });
    return () => { active = false; };
  }, [currentProjectId]);

  const handleDuplicateProject = async () => {
    if (!currentProject || isDuplicating || isDeletingProject) return;
    setIsDuplicating(true);
    setProjectActionError('');
    try {
      const duplicate = await duplicateProject(currentProject.id);
      if (duplicate) selectProject(duplicate);
    } catch (error) {
      setProjectActionError(error instanceof Error ? error.message : 'Failed to duplicate project');
    } finally {
      setIsDuplicating(false);
    }
  };

  const handleMergeProject = async (targetProjectId: string, mode: ProjectMergeMode) => {
    if (!mergeSourceProject) return null;
    return mergeProject(mergeSourceProject.id, targetProjectId, mode);
  };

  const handleDeleteProject = async () => {
    if (!currentProject || !canManageProject || isDeletingProject) return;
    const projectId = currentProject.id;
    if (!confirm(
      `Move "${currentProject.name}" to Trash? You can restore it until it expires.`,
    )) return;

    setIsDeletingProject(true);
    setProjectActionError('');
    try {
      await deleteProject(projectId);
    } catch (error) {
      setProjectActionError(error instanceof Error ? error.message : 'Failed to delete project');
    } finally {
      setIsDeletingProject(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    let current = true;
    setWatchedFolderPath('');
    setWatchedFolderEnabled(false);
    setWatchedFolderError('');
    if (!currentProjectId || !canManageProject) return () => { current = false; };

    api.getWatchedFolder(currentProjectId).then((settings) => {
      if (!current) return;
      setWatchedFolderEnabled(settings.enabled);
      setWatchedFolderPath(settings.path ?? '');
    }).catch((error) => {
      if (current) {
        setWatchedFolderError(error instanceof Error ? error.message : 'Could not load folder settings');
      }
    });

    return () => { current = false; };
  }, [currentProjectId, canManageProject]);

  useEffect(() => {
    if (!currentProjectId || !canManageProject || !watchedFolderPath) return;
    const interval = setInterval(() => {
      void refreshDocuments(currentProjectId);
    }, 60_000);
    return () => clearInterval(interval);
  }, [canManageProject, currentProjectId, refreshDocuments, watchedFolderPath]);

  useEffect(() => {
    if (!pendingSearchPreview) return;
    if (currentProjectId !== pendingSearchPreview.projectId) {
      setPendingSearchPreview(null);
      return;
    }
    const document = documents.find((item) => item.id === pendingSearchPreview.documentId);
    if (document) {
      setPreviewDocument(document);
      setPreviewCitation(null);
      setPendingSearchPreview(null);
    } else if (!loadingDocuments) {
      setPendingSearchPreview(null);
    }
  }, [currentProjectId, documents, loadingDocuments, pendingSearchPreview]);

  useEffect(() => {
    if (!citationPreview) return;
    setPreviewDocument(citationPreview.document);
    setPreviewCitation(citationPreview.citation);
    clearCitationPreview();
  }, [citationPreview, clearCitationPreview]);

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
    if (!currentProject || !canManageSources) {
      alert('Please select or create a project first');
      return;
    }

    const projectId = currentProject.id;
    const uploadSession = modalSession;
    if (items.length > 0 && typeof items[0] === 'string') {
      const result = await api.uploadUrlBatch(projectId, items as string[]);
      await refreshDocuments(projectId);
      if (!result.failures.length && !result.truncated) {
        if (
          modalSessionRef.current === uploadSession
          && isAddSourcesOpenRef.current
        ) {
          onAddSourcesOpenChange(false);
        }
      }
      return result;
    }

    await closeAddSourcesAfterSuccessfulUpload(async () => {
      for (const item of items) {
        await uploadDocument(projectId, item as File);
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
    if (!currentProject || !canManageSources) return;

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

  const handleDeleteDocument = async (document: Document) => {
    if (!currentProject) return;
    const confirmation = document.isOwnedByCaller
      ? `Move "${document.name}" to Trash? It will be removed from all projects and can be restored until it expires.`
      : `Remove "${document.name}" from this project?`;
    if (confirm(confirmation)) {
      try {
        if (document.isOwnedByCaller) {
          await api.trashSource(document.id);
          await refreshDocuments(currentProject.id);
        } else {
          await deleteDocument(currentProject.id, document.id);
        }
      } catch (error) {
        console.error('Failed to remove source:', error);
        alert('Failed to remove source');
      }
    }
  };

  const saveWatchedFolder = async (path: string | null) => {
    if (!currentProject || !canManageProject || watchedFolderSaving) return;
    const projectId = currentProject.id;
    setWatchedFolderSaving(true);
    setWatchedFolderError('');
    try {
      const settings = await api.setWatchedFolder(projectId, path);
      setWatchedFolderPath(settings.path ?? '');
      setWatchedFolderEnabled(settings.enabled);
      await refreshDocuments(projectId);
    } catch (error) {
      setWatchedFolderError(error instanceof Error ? error.message : 'Could not save folder settings');
    } finally {
      setWatchedFolderSaving(false);
    }
  };

  const handleResyncDocument = async (documentId: string) => {
    if (!currentProject || resyncingDocumentId) return;
    const projectId = currentProject.id;
    setResyncingDocumentId(documentId);
    try {
      await api.resyncDocument(projectId, documentId);
      await refreshDocuments(projectId);
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Could not re-sync source');
    } finally {
      setResyncingDocumentId(null);
    }
  };

  const saveProjectTags = async (tags: string[]): Promise<boolean> => {
    if (!currentProject || tagSaving) return false;
    setTagSaving(true);
    setTagError('');
    try {
      await updateProjectTags(currentProject.id, tags);
      return true;
    } catch (error) {
      setTagError(error instanceof Error ? error.message : 'Could not save project tags');
      return false;
    } finally {
      setTagSaving(false);
    }
  };

  const addProjectTag = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const tag = tagInput.trim();
    const tags = currentProject?.tags ?? [];
    if (!tag || tags.some((value) => value.toLowerCase() === tag.toLowerCase())) return;
    if (await saveProjectTags([...tags, tag])) setTagInput('');
  };

  const saveSourceGroups = (projectId: string, groups: ProjectSourceGroup[]) => {
    if (currentProjectId === projectId) setSourceGroupsState({ projectId, groups });
  };

  const createSourceGroup = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = newSourceGroupName.trim();
    if (!currentProjectId || !name || sourceGroupSaving || savingGroupDocumentId) return;
    setSourceGroupSaving(true);
    setSourceGroupError('');
    try {
      const group = await api.createProjectSourceGroup(currentProjectId, name);
      saveSourceGroups(currentProjectId, [...sourceGroups, group]);
      setNewSourceGroupName('');
    } catch (error) {
      setSourceGroupError(error instanceof Error ? error.message : 'Could not create source group');
    } finally {
      setSourceGroupSaving(false);
    }
  };

  const renameSourceGroup = async (group: ProjectSourceGroup) => {
    if (!currentProjectId || sourceGroupSaving || savingGroupDocumentId) return;
    const name = prompt('Rename source group', group.name)?.trim();
    if (!name || name === group.name) return;
    setSourceGroupSaving(true);
    setSourceGroupError('');
    try {
      const renamed = await api.renameProjectSourceGroup(currentProjectId, group.id, name);
      saveSourceGroups(currentProjectId, sourceGroups.map((item) => (
        item.id === group.id ? renamed : item
      )));
    } catch (error) {
      setSourceGroupError(error instanceof Error ? error.message : 'Could not rename source group');
    } finally {
      setSourceGroupSaving(false);
    }
  };

  const deleteSourceGroup = async (group: ProjectSourceGroup) => {
    if (!currentProjectId || sourceGroupSaving || savingGroupDocumentId) return;
    if (!confirm(`Delete "${group.name}"? Its sources will remain in the project.`)) return;
    setSourceGroupSaving(true);
    setSourceGroupError('');
    try {
      await api.deleteProjectSourceGroup(currentProjectId, group.id);
      saveSourceGroups(currentProjectId, sourceGroups.filter((item) => item.id !== group.id));
    } catch (error) {
      setSourceGroupError(error instanceof Error ? error.message : 'Could not delete source group');
    } finally {
      setSourceGroupSaving(false);
    }
  };

  const moveDocumentToGroup = async (documentId: string, groupId: string | null) => {
    if (!currentProjectId || !canManageSources || sourceGroupSaving || savingGroupDocumentId) return;
    const projectId = currentProjectId;
    setSavingGroupDocumentId(documentId);
    setSourceGroupSaving(true);
    setSourceGroupError('');
    try {
      const groups = await api.setDocumentSourceGroup(projectId, documentId, groupId);
      saveSourceGroups(projectId, groups);
    } catch (error) {
      setSourceGroupError(error instanceof Error ? error.message : 'Could not move source');
    } finally {
      setSavingGroupDocumentId(null);
      setSourceGroupSaving(false);
    }
  };

  const openSearchResult = (projectId: string, documentId: string) => {
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    if (currentProject?.id !== projectId) selectProject(project);
    setPendingSearchPreview({ projectId, documentId });
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
  const selectableDocuments = documents.filter((doc) => doc.status !== 'error');
  const selectedCount = selectableDocuments.filter((doc) => !deselected.includes(doc.id)).length;
  const allSelected = selectedCount === selectableDocuments.length;

  // Filter documents based on search query
  const filteredDocuments = documents.filter(doc => 
    doc.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const availableTags = [...new Set(projects.flatMap((project) => project.tags ?? []))]
    .sort((left, right) => left.localeCompare(right));
  const filteredProjects = projects.filter((project) => (
    tagFilter.length === 0 || tagFilter.some((filter) => (
      project.tags?.some((tag) => tag.toLowerCase() === filter.toLowerCase())
    ))
  ));
  if (currentProject && !filteredProjects.some((project) => project.id === currentProject.id)) {
    filteredProjects.push(currentProject);
  }
  const groupedDocumentIds = new Set(sourceGroups.flatMap((group) => group.document_ids));
  const ungroupedDocuments = filteredDocuments.filter((doc) => !groupedDocumentIds.has(doc.id));

  const renderSourceRow = (doc: Document) => {
    const groupId = sourceGroups.find((group) => group.document_ids.includes(doc.id))?.id ?? '';
    return (
      <div
        key={doc.id}
        // Rows, not bordered cards: a list of peers read as a stack of boxes.
        className="relative px-2 py-2 rounded-md hover:bg-[var(--muted)] transition-base cursor-pointer group"
        onClick={() => { setPreviewCitation(null); setPreviewDocument(doc); }}
      >
        <div className="flex items-start gap-2.5">
          <input
            type="checkbox"
            checked={doc.status !== 'error' && !deselected.includes(doc.id)}
            disabled={doc.status === 'error'}
            onChange={() => toggleSourceSelected(currentProject!.id, doc.id)}
            onClick={(event) => event.stopPropagation()}
            aria-label={`Use ${doc.name} in answers and Studio`}
            className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--primary)] cursor-pointer"
          />
          <span className="mt-0.5 shrink-0 text-[var(--muted-foreground)] [&_svg]:h-4 [&_svg]:w-4">
            {getSourceIcon(doc.type)}
          </span>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-medium truncate" title={doc.name}>{doc.name}</h3>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
              {STATUS_LABELS[doc.status] ?? doc.status}
            </p>
            {canManageSources && sourceGroups.length > 0 && (
              <select
                aria-label={`Move ${doc.name} to group`}
                value={groupId}
                disabled={sourceGroupSaving || savingGroupDocumentId === doc.id}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => void moveDocumentToGroup(doc.id, event.target.value || null)}
                className="mt-1 max-w-full h-7 px-1.5 bg-[var(--card)] border border-[var(--input)] rounded text-xs"
              >
                <option value="">Ungrouped</option>
                {sourceGroups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
              </select>
            )}
            {doc.last_synced_at && (
              <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                Last synced <time dateTime={doc.last_synced_at}>{new Date(doc.last_synced_at).toLocaleString()}</time>
                {doc.last_sync_changed !== null && doc.last_sync_changed !== undefined
                  ? ` · ${doc.last_sync_changed ? 'Changed' : 'No changes'}`
                  : ''}
              </p>
            )}
            {doc.status === 'error' && doc.error_message && (
              <p className="text-xs text-[var(--error)] mt-1 break-words">{doc.error_message}</p>
            )}
          </div>
        </div>
        {/* Overlay actions save filename width until pointer or keyboard focus needs them. */}
        <div className="absolute right-1.5 top-1.5 flex items-center gap-0.5 rounded bg-[var(--muted)] pl-1 opacity-0 transition-colors group-hover:opacity-100 group-focus-within:opacity-100">
          <button
            onClick={(event) => {
              event.stopPropagation();
              setPreviewCitation(null);
              setPreviewDocument(doc);
            }}
            className="p-1 hover:bg-[var(--card)] rounded"
            aria-label="Preview document"
            title="Preview document"
          >
            <Eye className="w-3 h-3" />
          </button>
          {doc.isOwnedByCaller && (
            <button
              onClick={(event) => { event.stopPropagation(); void handleRenameDocument(doc); }}
              className="p-1 hover:bg-[var(--muted)] rounded"
              aria-label="Rename document"
              title="Rename document"
            >
              <Pencil className="w-3 h-3" />
            </button>
          )}
          {canManageSources && (doc.type === 'url' || doc.type === 'youtube') && (
            <button
              type="button"
              onClick={(event) => { event.stopPropagation(); void handleResyncDocument(doc.id); }}
              disabled={Boolean(resyncingDocumentId) || ['queued', 'processing', 'transcribing'].includes(doc.status)}
              className="p-1 hover:bg-[var(--card)] rounded disabled:opacity-50"
              aria-label="Re-sync source"
              title="Re-sync source"
            >
              {resyncingDocumentId === doc.id
                ? <Loader2 className="w-3 h-3 animate-spin" />
                : <RefreshCw className="w-3 h-3" />}
            </button>
          )}
          {canManageSources && (
            <button
                onClick={(event) => { event.stopPropagation(); void handleDeleteDocument(doc); }}
              className="p-1 hover:bg-[var(--card)] rounded"
                aria-label={doc.isOwnedByCaller ? 'Move source to Trash' : 'Remove source'}
                title={doc.isOwnedByCaller ? 'Move source to Trash' : 'Remove source'}
            >
              {doc.isOwnedByCaller
                ? <Trash2 aria-hidden="true" className="w-3 h-3" />
                : <X aria-hidden="true" className="w-3 h-3" />}
            </button>
          )}
        </div>
      </div>
    );
  };

  const renderSourceSection = (
    key: string,
    name: string,
    visibleDocs: Document[],
    selectableDocs: Document[],
  ) => {
    const selected = selectableDocs.filter((doc) => !deselected.includes(doc.id)).length;
    const checked = selectableDocs.length > 0 && selected === selectableDocs.length;
    const label = key === 'ungrouped' ? 'Select ungrouped sources' : `Select sources in ${name}`;
    return (
      <div key={key} className="flex items-start gap-2 rounded-md border border-[var(--input)] px-2">
          <input
            type="checkbox"
            aria-label={label}
            checked={checked}
            disabled={selectableDocs.length === 0}
            ref={(input) => {
              if (input) input.indeterminate = selected > 0 && !checked;
            }}
            onClick={(event) => event.stopPropagation()}
            onChange={() => currentProject && setSourcesSelected(
              currentProject.id,
              selectableDocs.map((doc) => doc.id),
              !checked,
            )}
            className="mt-2 h-4 w-4 shrink-0 accent-[var(--primary)]"
          />
          <details open className="min-w-0 flex-1">
            <summary className="flex cursor-pointer list-none items-center gap-2 py-2 text-xs text-[var(--muted-foreground)]">
              <span className="flex-1 font-medium text-[var(--foreground)]">{name}</span>
              <span>{selected} of {selectableDocs.length} selected</span>
            </summary>
            <div className="space-y-0.5 pb-1">{visibleDocs.map(renderSourceRow)}</div>
          </details>
      </div>
    );
  };

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
        
        {/* Cover, project selector and New Project share one row; the project
            actions sit under it as one quiet row. Stacked full-width buttons
            took ~130px of a column that also has to hold the source list. */}
        <div className="mb-2 space-y-1.5">
          <div className="flex items-center gap-2">
            {currentProject && (
              <ProjectCover
                emoji={currentProject.cover_emoji}
                color={currentProject.cover_color}
                className="w-9 h-9 text-base shrink-0"
              />
            )}
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
              {filteredProjects.map((project) => (
                <option
                  key={project.id}
                  value={project.id}
                  data-cover-color={findProjectCoverColor(project.cover_color)?.id}
                  style={projectCoverStyle(project.cover_color)}
                >
                  {project.cover_emoji ? `${project.cover_emoji} ` : ''}{project.name}
                  {project.role !== 'owner' ? ` · Shared (${project.role})` : ''}
                </option>
              ))}
            </select>
            <button
              onClick={() => openProjectDialog()}
              aria-label="New Project"
              title="New Project"
              className="shrink-0 h-9 w-9 flex items-center justify-center border border-[var(--input)] bg-[var(--card)] rounded-md hover:bg-[var(--muted)] transition-base disabled:opacity-50"
            >
              <FolderOpen className="w-4 h-4" />
            </button>
          </div>
          <ProjectSearch onOpenResult={openSearchResult} />
          {availableTags.length > 0 && (
            <details className="rounded-md border border-[var(--input)] px-2 py-1.5">
              <summary className="cursor-pointer text-xs font-medium">Filter projects by tag</summary>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                {availableTags.map((tag) => (
                  <label key={tag} className="inline-flex items-center gap-1.5 text-xs">
                    <input
                      type="checkbox"
                      aria-label={`Filter by tag ${tag}`}
                      checked={tagFilter.some((value) => value.toLowerCase() === tag.toLowerCase())}
                      onChange={(event) => setTagFilter((selected) => event.target.checked
                        ? [...selected, tag]
                        : selected.filter((value) => value.toLowerCase() !== tag.toLowerCase()))}
                      className="h-3.5 w-3.5 accent-[var(--primary)]"
                    />
                    {tag}
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Projects with any selected tag are shown.</p>
            </details>
          )}
          {canManageProject && currentProject && (
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => openProjectDialog(currentProject)}
                disabled={isDeletingProject}
                className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-base disabled:opacity-50"
              >
                <Pencil className="w-3.5 h-3.5" />
                <span>Edit Project</span>
              </button>
              <button
                type="button"
                onClick={handleDuplicateProject}
                disabled={isDuplicating || isDeletingProject || isMergeDialogOpen}
                className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-base disabled:opacity-50"
              >
                {isDuplicating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{isDuplicating ? 'Duplicating...' : 'Duplicate Project'}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setMergeSourceProject(currentProject);
                  setIsMergeDialogOpen(true);
                }}
                disabled={isDuplicating || isDeletingProject || mergeTargets.length === 0}
                className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-base disabled:opacity-50"
              >
                <ArrowRightLeft className="w-3.5 h-3.5" />
                <span>Merge Project</span>
              </button>
              <button
                type="button"
                onClick={handleDeleteProject}
                disabled={isDeletingProject || isDuplicating || isMergeDialogOpen}
                className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-xs text-[var(--error)] hover:bg-[var(--muted)] transition-base disabled:opacity-50"
              >
                {isDeletingProject ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                <span>{isDeletingProject ? 'Moving...' : 'Move Project to Trash'}</span>
              </button>
              <button
                type="button"
                onClick={() => setIsAnalyticsOpen(true)}
                disabled={isDeletingProject}
                className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] transition-base disabled:opacity-50"
              >
                <BarChart3 className="w-3.5 h-3.5" />
                <span>Analytics</span>
              </button>
              {projectActionError && (
                <p role="alert" className="w-full px-2 text-xs text-[var(--error)]">{projectActionError}</p>
              )}
            </div>
          )}
        </div>

        {currentProject && (
          <details className="mb-2 rounded-md border border-[var(--input)] px-2.5 py-2">
            <summary className="cursor-pointer text-xs font-medium">My project tags</summary>
            <div className="mt-2 space-y-2">
              <p className="text-xs text-[var(--muted-foreground)]">
                These tags are private to your account.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {(currentProject.tags ?? []).map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2 py-1 text-xs">
                    {tag}
                    <button
                      type="button"
                      aria-label={`Remove tag ${tag}`}
                      disabled={tagSaving}
                      onClick={() => void saveProjectTags(
                        (currentProject.tags ?? []).filter((value) => value !== tag),
                      )}
                      className="rounded hover:text-[var(--error)] disabled:opacity-50"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <form onSubmit={(event) => void addProjectTag(event)} className="flex gap-1.5">
                <input
                  type="text"
                  aria-label="Add a tag"
                  value={tagInput}
                  maxLength={50}
                  onChange={(event) => setTagInput(event.target.value)}
                  placeholder="Add a tag"
                  disabled={tagSaving}
                  className="min-w-0 flex-1 h-8 px-2 bg-[var(--card)] border border-[var(--input)] rounded-md text-xs"
                />
                <button
                  type="submit"
                  disabled={tagSaving || !tagInput.trim()}
                  className="h-8 px-2 rounded-md border border-[var(--input)] text-xs disabled:opacity-50"
                >
                  {tagSaving ? 'Saving...' : 'Add tag'}
                </button>
              </form>
              {tagError && <p role="alert" className="text-xs text-[var(--error)]">{tagError}</p>}
            </div>
          </details>
        )}

        {currentProject && (
          <details className="mb-2 rounded-md border border-[var(--input)] px-2.5 py-2">
            <summary className="cursor-pointer text-xs font-medium">Source groups</summary>
            <div className="mt-2 space-y-2">
              {canManageSources && (
                <form onSubmit={(event) => void createSourceGroup(event)} className="flex gap-1.5">
                  <input
                    type="text"
                    aria-label="New source group"
                    value={newSourceGroupName}
                    maxLength={100}
                    onChange={(event) => setNewSourceGroupName(event.target.value)}
                    placeholder="New group name"
                    disabled={sourceGroupSaving || Boolean(savingGroupDocumentId)}
                    className="min-w-0 flex-1 h-8 px-2 bg-[var(--card)] border border-[var(--input)] rounded-md text-xs"
                  />
                  <button
                    type="submit"
                    disabled={sourceGroupSaving || Boolean(savingGroupDocumentId) || !newSourceGroupName.trim()}
                    className="h-8 px-2 rounded-md border border-[var(--input)] text-xs disabled:opacity-50"
                  >
                    Create group
                  </button>
                </form>
              )}
              {sourceGroups.length > 0 ? (
                <ul className="space-y-1">
                  {sourceGroups.map((group) => (
                    <li key={group.id} className="flex items-center gap-2 text-xs">
                      <span className="flex-1 truncate">{group.name}</span>
                      {canManageSources && (
                        <>
                          <button
                            type="button"
                            aria-label={`Rename ${group.name}`}
                            disabled={sourceGroupSaving || Boolean(savingGroupDocumentId)}
                            onClick={() => void renameSourceGroup(group)}
                            className="hover:underline disabled:opacity-50"
                          >Rename</button>
                          <button
                            type="button"
                            aria-label={`Delete ${group.name}`}
                            disabled={sourceGroupSaving || Boolean(savingGroupDocumentId)}
                            onClick={() => void deleteSourceGroup(group)}
                            className="text-[var(--error)] hover:underline disabled:opacity-50"
                          >Delete</button>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[var(--muted-foreground)]">No source groups yet.</p>
              )}
            </div>
          </details>
        )}

        {canManageProject && currentProject && (
          <details className="mb-2 rounded-md border border-[var(--input)] px-2.5 py-2">
            <summary className="cursor-pointer text-xs font-medium">Watch a server folder</summary>
            <div className="mt-2 space-y-2">
              <p className="text-xs text-[var(--muted-foreground)]">
                Files are checked every minute. Enter a path inside the server’s configured folder root.
              </p>
              {!watchedFolderEnabled && (
                <p className="text-xs text-[var(--muted-foreground)]">
                  Folder watching is not enabled by this server.
                </p>
              )}
              <label className="block text-xs" htmlFor="watched-folder-path">Server folder path</label>
              <input
                id="watched-folder-path"
                type="text"
                value={watchedFolderPath}
                onChange={(event) => setWatchedFolderPath(event.target.value)}
                placeholder="/app/watched-folders/project"
                disabled={!watchedFolderEnabled || watchedFolderSaving}
                className="w-full h-8 px-2 bg-[var(--card)] border border-[var(--input)] rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-50"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void saveWatchedFolder(watchedFolderPath.trim() || null)}
                  disabled={!watchedFolderEnabled || watchedFolderSaving || !watchedFolderPath.trim()}
                  className="h-7 px-2 rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] text-xs disabled:opacity-50"
                >
                  {watchedFolderSaving ? 'Saving...' : 'Save folder'}
                </button>
                {watchedFolderPath && (
                  <button
                    type="button"
                    onClick={() => void saveWatchedFolder(null)}
                    disabled={watchedFolderSaving}
                    className="h-7 px-2 rounded-md text-xs hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    Stop watching
                  </button>
                )}
              </div>
              {watchedFolderError && <p role="status" className="text-xs text-[var(--error)]">{watchedFolderError}</p>}
            </div>
          </details>
        )}
        
        {/* Add Source Button */}
        {canManageSources && currentProject && (
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
          {sourceGroupError && <p role="alert" className="mb-2 px-2 text-xs text-[var(--error)]">{sourceGroupError}</p>}
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
              {!searchQuery && canManageSources && (
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
                  disabled={selectableDocuments.length === 0}
                  ref={(input) => {
                    if (input) input.indeterminate = selectedCount > 0 && !allSelected;
                  }}
                  onChange={() => setAllSourcesSelected(currentProject.id, !allSelected)}
                  className="h-4 w-4 accent-[var(--primary)]"
                />
                <span className="flex-1">Select all sources</span>
                <span>{selectedCount} of {selectableDocuments.length} selected</span>
              </label>
              {sourceGroups.map((group) => {
                const groupDocumentIds = new Set(group.document_ids);
                const visibleDocs = filteredDocuments.filter((doc) => groupDocumentIds.has(doc.id));
                if (searchQuery && visibleDocs.length === 0) return null;
                const selectableDocs = documents.filter((doc) => (
                  groupDocumentIds.has(doc.id) && doc.status !== 'error'
                ));
                return renderSourceSection(group.id, group.name, visibleDocs, selectableDocs);
              })}
              {renderSourceSection(
                'ungrouped',
                'Ungrouped',
                ungroupedDocuments,
                documents.filter((doc) => !groupedDocumentIds.has(doc.id) && doc.status !== 'error'),
              )}
            </div>
          )}
        </div>
      )}
      </div>

      {/* Upload Modal */}
      {isAddSourcesOpen && canManageSources && currentProject && (
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
              multiple
              onUpload={handleUpload}
              onDiscover={(query) => api.discoverSources(currentProject.id, query)}
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
          citation={previewCitation ?? undefined}
          onClose={() => { setPreviewDocument(null); setPreviewCitation(null); }}
        />
      )}
      {canManageProject && currentProject && (
        <ProjectAnalyticsDialog
          project={currentProject}
          isOpen={isAnalyticsOpen}
          onClose={() => setIsAnalyticsOpen(false)}
        />
      )}
      {isMergeDialogOpen && mergeSourceProject && (
        <ProjectMergeDialog
          sourceProject={mergeSourceProject}
          projects={projects}
          onClose={() => {
            setIsMergeDialogOpen(false);
            setMergeSourceProject(null);
          }}
          onMerge={handleMergeProject}
        />
      )}
    </aside>
  );
}
