'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { 
  Mic,
  Video,
  FileText,
  Brain,
  ChevronDown,
  PanelRightClose,
  PanelRightOpen,
  Loader2,
  Square,
  Table,
} from 'lucide-react';
import useStore, { selectedSourceIds } from '@/store/useStore';
import useNotes from '@/store/useNotes';
import api, { ApiError } from '@/lib/api';
import type {
  MindMap,
  StudioNoteKind,
  StudioOutputOptions,
  VideoSummary,
} from '@/lib/api';
import { isSpeechSupported, speakText, stopSpeaking, summaryToSpeech } from '@/lib/speech';
import NotesSection from './NotesSection';

const MindMapDialog = React.lazy(() => import('@/components/MindMapDialog'));
const VideoSummaryDialog = React.lazy(() => import('@/components/VideoSummaryDialog'));
const AudioOverviewDialog = React.lazy(() => import('@/components/AudioOverviewDialog'));
const StudyToolsDialog = React.lazy(() => import('@/components/StudyToolsDialog'));
const ReportDialog = React.lazy(() => import('@/components/ReportDialog'));
const DataTableDialog = React.lazy(() => import('@/components/DataTableDialog'));

interface ProjectResult<T> {
  projectId: string;
  cacheKey: string;
  options: StudioOutputOptions;
  value: T;
}

const STUDIO_OPTIONS_STORAGE_KEY = 'studio-output-options';
const DEFAULT_STUDIO_OPTIONS: Required<StudioOutputOptions> = {
  focus: null,
  audience: 'general',
  length: 'default',
};

const readStudioOptions = (projectId: string): Required<StudioOutputOptions> => {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(`${STUDIO_OPTIONS_STORAGE_KEY}:${projectId}`) ?? 'null',
    );
    return {
      focus: typeof saved?.focus === 'string' ? saved.focus.slice(0, 500) : null,
      audience: ['general', 'beginner', 'expert'].includes(saved?.audience)
        ? saved.audience
        : 'general',
      length: ['short', 'default', 'long'].includes(saved?.length)
        ? saved.length
        : 'default',
    };
  } catch {
    return DEFAULT_STUDIO_OPTIONS;
  }
};

const studioResultKey = (
  projectId: string,
  documentIds: string[] | undefined,
  options: StudioOutputOptions | undefined,
  languageRevision: number,
) => JSON.stringify([
  projectId,
  documentIds ?? null,
  options ?? DEFAULT_STUDIO_OPTIONS,
  languageRevision,
]);

async function saveStudioNote(
  projectId: string,
  title: string,
  fields: { studio_kind: StudioNoteKind } & {
    content?: string;
    payload_json?: MindMap | VideoSummary;
  },
): Promise<void> {
  const note = await api.createNote(projectId, { title: title.slice(0, 200), ...fields });
  useNotes.getState().upsert(note);
}

const StudioDialogFallback = () => (
  <div
    role="status"
    aria-live="polite"
    aria-label="Loading studio result"
    className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]"
  >
    <span className="inline-flex items-center gap-2 rounded-lg bg-[var(--card)] px-4 py-3 text-sm">
      <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
      Loading studio result…
    </span>
  </div>
);

interface StudioOption {
  id: string;
  title: string;
  icon: React.ReactNode;
  /** Outputs with no backend endpoint stay unavailable. */
  available?: boolean;
  /** Distinguishes the live actions from one another. */
  action?: 'report' | 'audio' | 'mindmap' | 'video' | 'table';
}

type CustomizableStudioAction = Exclude<StudioOption['action'], 'table' | undefined>;

interface StudioPanelProps {
  isCollapsed?: boolean;
  onCollapsedChange?: (isCollapsed: boolean) => void;
  outputLanguageRevision?: number;
}

export default function StudioPanel({
  isCollapsed = false,
  onCollapsedChange,
  outputLanguageRevision = 0,
}: StudioPanelProps) {
  const availabilityLabel = 'coming soon';
  const optionHintIdPrefix = useId();
  const currentProject = useStore((state) => state.currentProject);
  const canEditProject = currentProject?.role === 'owner' || currentProject?.role === 'editor';
  const documents = useStore((state) => state.documents);
  const deselectedSources = useStore((state) => state.deselectedSources);
  const loadingDocuments = useStore((state) => state.loadingDocuments);
  const noSourcesSelected = selectedSourceIds({
    currentProject, documents, deselectedSources,
  })?.length === 0;
  const [reportError, setReportError] = useState('');
  const [reportDialog, setReportDialog] = useState<{
    projectId: string;
    projectName: string;
    documentIds?: string[];
    options?: StudioOutputOptions;
  } | null>(null);
  const [tableDialog, setTableDialog] = useState<{
    projectId: string;
    projectName: string;
    sourceIds?: string[];
  } | null>(null);
  const [isPreparingAudio, setIsPreparingAudio] = useState(false);
  const [isBuildingMindMap, setIsBuildingMindMap] = useState(false);
  const [mindMap, setMindMap] = useState<ProjectResult<MindMap> | null>(null);
  const [isPreparingVideo, setIsPreparingVideo] = useState(false);
  const [videoSummary, setVideoSummary] = useState<ProjectResult<VideoSummary> | null>(null);
  const [isMoreOptionsOpen, setIsMoreOptionsOpen] = useState(false);
  const [customizeAction, setCustomizeAction] = useState<CustomizableStudioAction | null>(null);
  const [customizeProjectId, setCustomizeProjectId] = useState<string | null>(null);
  const [customizeOptions, setCustomizeOptions] = useState<Required<StudioOutputOptions>>(DEFAULT_STUDIO_OPTIONS);
  const [audioOverviewOptions, setAudioOverviewOptions] = useState<StudioOutputOptions>();
  const [studyDialog, setStudyDialog] = useState<{
    projectId: string;
    mode: 'flashcards' | 'quiz';
    documentIds: string[];
  } | null>(null);
  const moreOptionsRef = useRef<HTMLButtonElement>(null);
  const focusId = useId();
  const audienceId = useId();
  const lengthId = useId();
  const [audioOverviewCapability, setAudioOverviewCapability] = useState<{
    projectId: string;
    enabled: boolean;
  } | null>(null);
  const [isCheckingAudioCapability, setIsCheckingAudioCapability] = useState(false);
  const [isAudioOverviewOpen, setIsAudioOverviewOpen] = useState(false);
  const audioOverviewCapabilityKnown = Boolean(
    currentProject && audioOverviewCapability?.projectId === currentProject.id,
  );
  const audioOverviewTtsEnabled = audioOverviewCapabilityKnown
    ? audioOverviewCapability?.enabled ?? true
    : true;
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(true);
  // Identifies the reading in progress. Stopping retires it, so anything the
  // browser reports about it afterwards cannot disturb the panel — or a reading
  // the listener has since started.
  const playbackRun = useRef(0);
  const projectGeneration = useRef(0);

  const beginProjectOperation = () => {
    if (!currentProject) return null;

    const project = currentProject;
    const generation = projectGeneration.current;
    return {
      project,
      isCurrent: () => (
        projectGeneration.current === generation
        && useStore.getState().currentProject?.id === project.id
      ),
    };
  };

  // Speech support can only be read in the browser, so check after mount to
  // keep the server-rendered markup stable.
  useEffect(() => {
    setSpeechSupported(isSpeechSupported());
    return () => {
      playbackRun.current += 1;
      stopSpeaking();
    };
  }, []);

  useEffect(() => {
    projectGeneration.current += 1;
    playbackRun.current += 1;
    stopSpeaking();
    setIsPreparingAudio(false);
    setIsSpeaking(false);
    setIsCheckingAudioCapability(false);
    setIsBuildingMindMap(false);
    setIsPreparingVideo(false);
    setMindMap(null);
    setReportDialog(null);
    setTableDialog(null);
    setVideoSummary(null);
    setStudyDialog(null);
    setIsMoreOptionsOpen(false);
    setIsAudioOverviewOpen(false);
    setCustomizeAction(null);
    setCustomizeProjectId(null);
    setAudioOverviewOptions(undefined);
    setReportError('');
  }, [currentProject?.id, outputLanguageRevision]);

  const playAudioSummary = async (options?: StudioOutputOptions) => {
    const operation = beginProjectOperation();
    if (!operation) return;

    const run = playbackRun.current + 1;
    playbackRun.current = run;
    const isCurrent = () => playbackRun.current === run && operation.isCurrent();

    setIsPreparingAudio(true);
    setReportError('');

    try {
      const documentIds = selectedSourceIds(useStore.getState());
      const summary = options
        ? await api.fetchProjectSummaryText(operation.project.id, documentIds, options)
        : await api.fetchProjectSummaryText(operation.project.id, documentIds);
      const spoken = summaryToSpeech(summary);
      if (!isCurrent()) return;

      setIsPreparingAudio(false);
      setIsSpeaking(true);
      await speakText(spoken);
    } catch {
      if (isCurrent()) {
        setReportError('The audio summary could not be read out. Please try again.');
      }
    } finally {
      if (isCurrent()) {
        setIsPreparingAudio(false);
        setIsSpeaking(false);
      }
    }
  };

  const stopAudioSummary = () => {
    playbackRun.current += 1;
    stopSpeaking();
    setIsPreparingAudio(false);
    setIsSpeaking(false);
  };

  const openAudioOverview = async (options?: StudioOutputOptions) => {
    const operation = beginProjectOperation();
    if (!operation) return;
    setAudioOverviewOptions(options);
    setIsCheckingAudioCapability(true);
    setReportError('');
    try {
      const { enabled } = await api.listAudioOverviews(operation.project.id);
      if (!operation.isCurrent()) return;
      setAudioOverviewCapability({ projectId: operation.project.id, enabled });
      if (enabled) {
        setIsAudioOverviewOpen(true);
      } else if (speechSupported) {
        setIsCheckingAudioCapability(false);
        await playAudioSummary(options);
      } else {
        setReportError('Audio playback is not supported in this browser.');
      }
    } catch {
      if (operation.isCurrent()) {
        setReportError('Audio summary availability could not be checked. Please try again.');
      }
    } finally {
      if (operation.isCurrent()) setIsCheckingAudioCapability(false);
    }
  };

  const buildMindMap = async (options?: StudioOutputOptions) => {
    const operation = beginProjectOperation();
    if (!operation) return;
    const documentIds = selectedSourceIds(useStore.getState());
    const cacheKey = studioResultKey(
      operation.project.id, documentIds, options, outputLanguageRevision,
    );

    setIsBuildingMindMap(true);
    setReportError('');

    try {
      const map = options
        ? await api.fetchProjectMindMap(operation.project.id, documentIds, options)
        : await api.fetchProjectMindMap(operation.project.id, documentIds);
      if (operation.isCurrent()) {
        setMindMap({
          projectId: operation.project.id,
          cacheKey,
          options: options ?? DEFAULT_STUDIO_OPTIONS,
          value: map,
        });
      }
    } catch {
      if (operation.isCurrent()) {
        setReportError('The mind map could not be built. Please try again.');
      }
    } finally {
      if (operation.isCurrent()) setIsBuildingMindMap(false);
    }
  };

  const playVideoSummary = async (options?: StudioOutputOptions) => {
    const operation = beginProjectOperation();
    if (!operation) return;
    const documentIds = selectedSourceIds(useStore.getState());
    const cacheKey = studioResultKey(
      operation.project.id, documentIds, options, outputLanguageRevision,
    );

    setIsPreparingVideo(true);
    setReportError('');

    try {
      const summary = options
        ? await api.fetchProjectVideoSummary(operation.project.id, documentIds, options)
        : await api.fetchProjectVideoSummary(operation.project.id, documentIds);
      if (operation.isCurrent()) {
        setVideoSummary({
          projectId: operation.project.id,
          cacheKey,
          options: options ?? DEFAULT_STUDIO_OPTIONS,
          value: summary,
        });
      }
    } catch (error) {
      if (operation.isCurrent()) {
        setReportError(
          error instanceof ApiError && error.status === 413
            ? 'This video summary is too large. Select fewer sources and try again.'
            : 'The video summary could not be prepared. Please try again.',
        );
      }
    } finally {
      if (operation.isCurrent()) setIsPreparingVideo(false);
    }
  };

  const openReport = (options?: StudioOutputOptions) => {
    if (!currentProject) return;
    setReportDialog({
      projectId: currentProject.id,
      projectName: currentProject.name,
      documentIds: selectedSourceIds(useStore.getState()),
      options,
    });
  };

  const openTable = () => {
    if (!currentProject) return;
    setTableDialog({
      projectId: currentProject.id,
      projectName: currentProject.name,
      sourceIds: selectedSourceIds(useStore.getState()),
    });
  };

  const openCustomize = (action: CustomizableStudioAction) => {
    if (!currentProject) return;
    setCustomizeProjectId(currentProject.id);
    setCustomizeAction(action);
    setCustomizeOptions(readStudioOptions(currentProject.id));
  };

  const updateCustomizeOptions = (changes: Partial<Required<StudioOutputOptions>>) => {
    const next = { ...customizeOptions, ...changes };
    setCustomizeOptions(next);
    if (customizeProjectId) {
      try {
        window.localStorage.setItem(
          `${STUDIO_OPTIONS_STORAGE_KEY}:${customizeProjectId}`,
          JSON.stringify(next),
        );
      } catch {
        // Private browsing can deny local storage; generation still uses the in-memory values.
      }
    }
  };

  const generateCustomized = () => {
    if (!customizeAction || customizeProjectId !== currentProject?.id) return;
    const options: StudioOutputOptions = {
      ...customizeOptions,
      focus: customizeOptions.focus?.trim() || null,
    };
    const action = customizeAction;
    setCustomizeAction(null);
    if (action === 'audio') void openAudioOverview(options);
    else if (action === 'mindmap') void buildMindMap(options);
    else if (action === 'video') void playVideoSummary(options);
    else if (action === 'report') openReport(options);
  };

  const optionAction = (option: StudioOption) => {
    if (option.action === 'report') return () => openReport();
    if (option.action === 'table') return openTable;
    if (option.action === 'mindmap') return () => buildMindMap();
    if (option.action === 'video') return () => playVideoSummary();
    if (option.action === 'audio') {
      if (!audioOverviewCapabilityKnown) return () => openAudioOverview();
      if (audioOverviewTtsEnabled) return () => {
        setAudioOverviewOptions(undefined);
        setIsAudioOverviewOpen(true);
      };
      return isSpeaking ? stopAudioSummary : () => playAudioSummary();
    }
    return undefined;
  };

  const openStudyTools = (mode: 'flashcards' | 'quiz') => {
    if (!currentProject) return;
    const state = useStore.getState();
    const selected = selectedSourceIds(state);
    const documentIds = state.documents
      .filter((document) => document.status === 'ready'
        && (!selected || selected.includes(document.id)))
      .map((document) => document.id);
    setIsMoreOptionsOpen(false);
    moreOptionsRef.current?.focus();
    setStudyDialog({ projectId: currentProject.id, mode, documentIds });
  };

  // A video summary of nothing is two empty slides, so the panel says so
  // instead of playing them. The project's own `document_count` is a snapshot
  // from the last project fetch and goes stale the moment a source is added or
  // removed, so read the list the rest of the workspace reads. An empty list
  // while it is still arriving means "not known yet", not "nothing to play".
  const hasNoSources = !loadingDocuments && documents.length === 0;
  // Effects clear old output after commit, but this gate prevents an open A
  // dialog from being rendered during the B commit that triggered that effect.
  const currentDocumentIds = selectedSourceIds(useStore.getState());
  const currentMindMap = mindMap !== null && mindMap.projectId === currentProject?.id
    && mindMap.cacheKey === studioResultKey(
      mindMap.projectId, currentDocumentIds, mindMap.options, outputLanguageRevision,
    )
    ? mindMap.value
    : null;
  const currentReportDialog = reportDialog?.projectId === currentProject?.id
    ? reportDialog
    : null;
  const currentVideoSummary = videoSummary !== null && videoSummary.projectId === currentProject?.id
    && videoSummary.cacheKey === studioResultKey(
      videoSummary.projectId, currentDocumentIds, videoSummary.options, outputLanguageRevision,
    )
    ? videoSummary.value
    : null;
  const currentStudyDialog = studyDialog?.projectId === currentProject?.id
    ? studyDialog
    : null;

  // A reading already under way stays stoppable after its sources are cleared.
  const blockedBySelection = (option: StudioOption) => (
    noSourcesSelected && !(option.action === 'audio'
      && audioOverviewCapabilityKnown && !audioOverviewTtsEnabled && isSpeaking)
  );

  const optionDisabled = (option: StudioOption) => {
    if (!option.available || !currentProject || blockedBySelection(option)) return true;
    if (option.action === 'audio') {
      return isCheckingAudioCapability
        || (audioOverviewCapabilityKnown && !audioOverviewTtsEnabled && !speechSupported)
        || isPreparingAudio;
    }
    if (option.action === 'mindmap') return isBuildingMindMap || currentMindMap !== null;
    if (option.action === 'table') return hasNoSources || tableDialog?.projectId === currentProject.id;
    if (option.action === 'video') {
      return isPreparingVideo || currentVideoSummary !== null || hasNoSources;
    }
    return reportDialog?.projectId === currentProject.id;
  };

  const optionLabel = (option: StudioOption) => {
    if (!option.available) return `${option.title} (${availabilityLabel})`;
    if (option.action === 'audio' && audioOverviewCapabilityKnown
      && !audioOverviewTtsEnabled && isSpeaking) {
      return 'Stop audio summary';
    }
    return option.title;
  };

  const optionIcon = (option: StudioOption) => {
    if (option.action === 'audio' && isCheckingAudioCapability) {
      return <Loader2 className="w-5 h-5 animate-spin" />;
    }
    if (option.action === 'audio' && !audioOverviewTtsEnabled) {
      if (isPreparingAudio) return <Loader2 className="w-5 h-5 animate-spin" />;
      if (isSpeaking) return <Square className="w-5 h-5" />;
      return option.icon;
    }

    if (option.action === 'mindmap' && isBuildingMindMap) {
      return <Loader2 className="w-5 h-5 animate-spin" />;
    }

    if (option.action === 'video' && isPreparingVideo) {
      return <Loader2 className="w-5 h-5 animate-spin" />;
    }

    return option.icon;
  };

  const optionHint = (option: StudioOption) => {
    if (!option.available) return availabilityLabel;
    if (!currentProject) return 'Select a project first';
    if (blockedBySelection(option)) return 'Select a source first';

    if (option.action === 'audio') {
      if (isCheckingAudioCapability) return 'Checking audio summary availability…';
      if (!audioOverviewCapabilityKnown) return 'Check audio summary availability';
      if (audioOverviewTtsEnabled) return 'Choose the format and length for this audio overview';
      if (!speechSupported) return 'Not supported in this browser';
      if (isPreparingAudio) return 'Preparing audio…';
      if (isSpeaking) return 'Playing — select to stop';
      return 'Listen to this project';
    }

    if (option.action === 'mindmap') {
      if (isBuildingMindMap) return 'Building the map…';
      return 'See how this project connects';
    }

    if (option.action === 'video') {
      if (hasNoSources) return 'Add a source first';
      if (isPreparingVideo) return 'Preparing the script…';
      return 'Watch a walkthrough of this project';
    }

    if (option.action === 'report') return 'Choose a format and create a cited report';
    if (option.action === 'table') return 'Extract and export a source comparison table';

    return 'Summarise this project';
  };

  const studioOptions: StudioOption[] = [
    {
      id: 'audio',
      available: true,
      action: 'audio',
      title: 'Audio summary',
      icon: <Mic className="w-5 h-5" />
    },
    {
      id: 'video',
      available: true,
      action: 'video',
      title: 'Video summary',
      icon: <Video className="w-5 h-5" />
    },
    {
      id: 'mindmap',
      available: true,
      action: 'mindmap',
      title: 'Mind map',
      icon: <Brain className="w-5 h-5" />
    },
    {
      id: 'report',
      available: true,
      action: 'report',
      title: 'Report',
      icon: <FileText className="w-5 h-5" />
    },
    {
      id: 'table',
      available: true,
      action: 'table',
      title: 'Data table',
      icon: <Table className="w-5 h-5" />
    }
  ];
  const customizedOption = studioOptions.find(
    (option) => option.action === customizeAction,
  );

  return (
    <aside
      aria-label="Studio"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-l border-[var(--border)] bg-[var(--sidebar-bg)] flex flex-col h-full"
    >
      {onCollapsedChange && (
        <button
          type="button"
          onClick={() => onCollapsedChange(!isCollapsed)}
          aria-controls="studio-panel-content"
          aria-expanded={!isCollapsed}
          aria-label={isCollapsed ? 'Expand Studio' : 'Collapse Studio'}
          title={isCollapsed ? 'Expand Studio' : 'Collapse Studio'}
          className="absolute top-2 right-2 z-10 p-1.5 hover:bg-[var(--muted)] rounded-lg transition-base"
        >
          {isCollapsed ? (
            <PanelRightOpen className="w-4 h-4" />
          ) : (
            <PanelRightClose className="w-4 h-4" />
          )}
        </button>
      )}

      <div
        id="studio-panel-content"
        role="region"
        aria-label="Studio panel content"
        hidden={isCollapsed}
        className="min-h-0 flex-1 flex flex-col"
      >
        {/* Header */}
        <div className="px-4 pt-4">
          <h2 className="pr-10 text-sm font-semibold">Studio</h2>
        </div>

        {/* Studio Options */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* One divided card of rows rather than four tinted tiles with an
              icon in a square each: the outputs are peers, and the tiles were
              the heaviest thing on the screen while doing the least. */}
          <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] divide-y divide-[var(--border)]">
            {studioOptions.map((option) => {
              const hint = optionHint(option);
              const hintId = `${optionHintIdPrefix}-${option.id}-hint`;
              const action = option.action;

              return (
                <div key={option.id} className="flex min-w-0 items-stretch">
                  <button
                    type="button"
                    onClick={optionAction(option)}
                    disabled={optionDisabled(option)}
                    aria-label={optionLabel(option)}
                    aria-describedby={hintId}
                    title={hint}
                    className="flex h-11 min-w-0 flex-1 items-center gap-3 px-3 text-left hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ring)] transition-base disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                  >
                    <span className="flex shrink-0 text-[var(--muted-foreground)] [&_svg]:h-4 [&_svg]:w-4">
                      {optionIcon(option)}
                    </span>
                    <h3 className="truncate text-sm font-medium">{option.title}</h3>
                    <span id={hintId} className="sr-only">{hint}</span>
                  </button>
                  {action && action !== 'table' && (
                    <button
                      type="button"
                      aria-label={`Customize ${option.title}`}
                      title={`Customize ${option.title}`}
                      disabled={optionDisabled(option)}
                      onClick={() => openCustomize(action)}
                      className="shrink-0 border-l border-[var(--border)] px-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Customize
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {customizeAction && customizeProjectId === currentProject?.id && (
            <form
              role="dialog"
                  aria-label={`Customize ${customizedOption?.title ?? 'Studio output'}`}
              onSubmit={(event) => {
                event.preventDefault();
                generateCustomized();
              }}
              className="mt-3 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--popover)] p-3"
            >
              <label htmlFor={focusId} className="block text-sm font-medium">Focus (optional)</label>
              <textarea
                id={focusId}
                value={customizeOptions.focus ?? ''}
                onChange={(event) => updateCustomizeOptions({
                  focus: event.target.value.slice(0, 500) || null,
                })}
                maxLength={500}
                rows={2}
                placeholder="Question or topic to focus on"
                className="w-full resize-y rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm"
              />
              <label htmlFor={audienceId} className="block text-sm font-medium">Audience</label>
              <select
                id={audienceId}
                value={customizeOptions.audience}
                onChange={(event) => updateCustomizeOptions({
                  audience: event.target.value as Required<StudioOutputOptions>['audience'],
                })}
                className="w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm"
              >
                <option value="general">General</option>
                <option value="beginner">Beginner</option>
                <option value="expert">Expert</option>
              </select>
              <label htmlFor={lengthId} className="block text-sm font-medium">Length</label>
              <select
                id={lengthId}
                value={customizeOptions.length}
                onChange={(event) => updateCustomizeOptions({
                  length: event.target.value as Required<StudioOutputOptions>['length'],
                })}
                className="w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-3 py-2 text-sm"
              >
                <option value="short">Short</option>
                <option value="default">Default</option>
                <option value="long">Long</option>
              </select>
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setCustomizeAction(null)}
                  className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)]">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!customizedOption || optionDisabled(customizedOption)}
                  className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-60">
                  Generate
                </button>
              </div>
            </form>
          )}

          {reportError && (
            <p role="alert" className="mt-3 text-xs text-[var(--error)]">
              {reportError}
            </p>
          )}

          <div className="relative mt-4">
            <button
              ref={moreOptionsRef}
              type="button"
              disabled={!currentProject || loadingDocuments}
              aria-label="More options"
              aria-expanded={isMoreOptionsOpen}
              aria-controls="studio-study-tools-menu"
              onClick={() => setIsMoreOptionsOpen(!isMoreOptionsOpen)}
              className="w-full rounded-lg p-3 text-sm text-[var(--muted-foreground)] flex flex-col items-center justify-center gap-0.5 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <span className="flex items-center gap-2">
                <span className="truncate">More options</span>
                <ChevronDown className="w-4 h-4 shrink-0" />
              </span>
              <span className="truncate text-xs">
                {!currentProject ? 'Select a project first'
                  : loadingDocuments ? 'Loading sources…' : 'Flashcards and practice quiz'}
              </span>
            </button>
            <div
              id="studio-study-tools-menu"
              role="group"
              aria-label="Study tools"
              hidden={!isMoreOptionsOpen}
              className="absolute inset-x-0 top-full z-10 mt-1 rounded-lg border border-[var(--border)] bg-[var(--popover)] p-1 shadow-lg"
            >
              <button type="button" onClick={() => openStudyTools('flashcards')}
                className="w-full rounded px-3 py-2 text-left text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]">
                Flashcards
              </button>
              <button type="button" onClick={() => openStudyTools('quiz')}
                className="w-full rounded px-3 py-2 text-left text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]">
                Practice quiz
              </button>
            </div>
          </div>

          <NotesSection projectId={currentProject?.id ?? null} />

        </div>
      </div>

      {currentMindMap && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <MindMapDialog
            map={currentMindMap}
            onClose={() => setMindMap(null)}
            onSave={canEditProject ? () => saveStudioNote(currentMindMap.project_id,
              `${currentMindMap.project_name} mind map`, {
                studio_kind: 'mindmap', payload_json: currentMindMap,
              }) : undefined}
            onAsk={(question) => {
              useStore.getState().draftMindMapQuestion(currentMindMap.project_id, question);
              setMindMap(null);
            }}
          />
        </React.Suspense>
      )}

      {currentReportDialog && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <ReportDialog
            key={currentReportDialog.projectId}
            projectId={currentReportDialog.projectId}
            projectName={currentReportDialog.projectName}
            documentIds={currentReportDialog.documentIds}
            options={currentReportDialog.options}
            onClose={() => setReportDialog(null)}
            onSave={canEditProject ? (markdown) => saveStudioNote(
              currentReportDialog.projectId,
              `${currentReportDialog.projectName} report`,
              { studio_kind: 'report', content: markdown },
            ) : undefined}
          />
        </React.Suspense>
      )}

      {tableDialog && tableDialog.projectId === currentProject?.id && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <DataTableDialog
            key={tableDialog.projectId}
            projectId={tableDialog.projectId}
            projectName={tableDialog.projectName}
            sourceIds={tableDialog.sourceIds}
            onClose={() => setTableDialog(null)}
          />
        </React.Suspense>
      )}

      {currentVideoSummary && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <VideoSummaryDialog
            summary={currentVideoSummary}
            onClose={() => setVideoSummary(null)}
            onSave={canEditProject ? () => saveStudioNote(currentVideoSummary.project_id,
              `${currentVideoSummary.project_name} video summary`, {
                studio_kind: 'video_summary', payload_json: currentVideoSummary,
              }) : undefined}
          />
        </React.Suspense>
      )}
      {currentStudyDialog && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <StudyToolsDialog
            key={`${currentStudyDialog.projectId}-${currentStudyDialog.mode}`}
            projectId={currentStudyDialog.projectId}
            mode={currentStudyDialog.mode}
            documentIds={currentStudyDialog.documentIds}
            onClose={() => {
              setStudyDialog(null);
              setIsMoreOptionsOpen(false);
            }}
          />
        </React.Suspense>
      )}
      {isAudioOverviewOpen && currentProject && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <AudioOverviewDialog
            projectId={currentProject.id}
            documentIds={selectedSourceIds(useStore.getState())}
            initialOptions={audioOverviewOptions}
            onClose={() => setIsAudioOverviewOpen(false)}
          />
        </React.Suspense>
      )}
    </aside>
  );
}
