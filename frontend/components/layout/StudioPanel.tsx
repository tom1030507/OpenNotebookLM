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
} from 'lucide-react';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { MindMap, VideoSummary } from '@/lib/api';
import { isSpeechSupported, speakText, stopSpeaking, summaryToSpeech } from '@/lib/speech';

const MindMapDialog = React.lazy(() => import('@/components/MindMapDialog'));
const VideoSummaryDialog = React.lazy(() => import('@/components/VideoSummaryDialog'));

interface ProjectResult<T> {
  projectId: string;
  value: T;
}

const StudioDialogFallback = () => (
  <div
    role="status"
    aria-live="polite"
    aria-label="Loading studio result"
    className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
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
  action?: 'report' | 'audio' | 'mindmap' | 'video';
}

interface StudioPanelProps {
  isCollapsed?: boolean;
  onCollapsedChange?: (isCollapsed: boolean) => void;
}

export default function StudioPanel({
  isCollapsed = false,
  onCollapsedChange,
}: StudioPanelProps) {
  const availabilityLabel = 'coming soon';
  const optionHintIdPrefix = useId();
  const currentProject = useStore((state) => state.currentProject);
  const documents = useStore((state) => state.documents);
  const loadingDocuments = useStore((state) => state.loadingDocuments);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [reportError, setReportError] = useState('');
  const [isPreparingAudio, setIsPreparingAudio] = useState(false);
  const [isBuildingMindMap, setIsBuildingMindMap] = useState(false);
  const [mindMap, setMindMap] = useState<ProjectResult<MindMap> | null>(null);
  const [isPreparingVideo, setIsPreparingVideo] = useState(false);
  const [videoSummary, setVideoSummary] = useState<ProjectResult<VideoSummary> | null>(null);
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
    setIsGeneratingReport(false);
    setIsPreparingAudio(false);
    setIsBuildingMindMap(false);
    setIsPreparingVideo(false);
    setMindMap(null);
    setVideoSummary(null);
    setReportError('');
  }, [currentProject?.id]);

  const playAudioSummary = async () => {
    const operation = beginProjectOperation();
    if (!operation) return;

    const run = playbackRun.current + 1;
    playbackRun.current = run;
    const isCurrent = () => playbackRun.current === run && operation.isCurrent();

    setIsPreparingAudio(true);
    setReportError('');

    try {
      const spoken = summaryToSpeech(await api.fetchProjectSummaryText(operation.project.id));
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

  const buildMindMap = async () => {
    const operation = beginProjectOperation();
    if (!operation) return;

    setIsBuildingMindMap(true);
    setReportError('');

    try {
      const map = await api.fetchProjectMindMap(operation.project.id);
      if (operation.isCurrent()) {
        setMindMap({ projectId: operation.project.id, value: map });
      }
    } catch {
      if (operation.isCurrent()) {
        setReportError('The mind map could not be built. Please try again.');
      }
    } finally {
      if (operation.isCurrent()) setIsBuildingMindMap(false);
    }
  };

  const playVideoSummary = async () => {
    const operation = beginProjectOperation();
    if (!operation) return;

    setIsPreparingVideo(true);
    setReportError('');

    try {
      const summary = await api.fetchProjectVideoSummary(operation.project.id);
      if (operation.isCurrent()) {
        setVideoSummary({ projectId: operation.project.id, value: summary });
      }
    } catch {
      if (operation.isCurrent()) {
        setReportError('The video summary could not be prepared. Please try again.');
      }
    } finally {
      if (operation.isCurrent()) setIsPreparingVideo(false);
    }
  };

  const generateReport = async () => {
    const operation = beginProjectOperation();
    if (!operation) return;

    setIsGeneratingReport(true);
    setReportError('');

    try {
      const blob = await api.exportProjectSummary(operation.project.id);
      if (!operation.isCurrent()) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${operation.project.name} report.md`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      if (operation.isCurrent()) {
        setReportError('The report could not be generated. Please try again.');
      }
    } finally {
      if (operation.isCurrent()) setIsGeneratingReport(false);
    }
  };
  const optionAction = (option: StudioOption) => {
    if (option.action === 'report') return generateReport;
    if (option.action === 'mindmap') return buildMindMap;
    if (option.action === 'video') return playVideoSummary;
    if (option.action === 'audio') return isSpeaking ? stopAudioSummary : playAudioSummary;
    return undefined;
  };

  // A video summary of nothing is two empty slides, so the panel says so
  // instead of playing them. The project's own `document_count` is a snapshot
  // from the last project fetch and goes stale the moment a source is added or
  // removed, so read the list the rest of the workspace reads. An empty list
  // while it is still arriving means "not known yet", not "nothing to play".
  const hasNoSources = !loadingDocuments && documents.length === 0;
  // Effects clear old output after commit, but this gate prevents an open A
  // dialog from being rendered during the B commit that triggered that effect.
  const currentMindMap = mindMap !== null && mindMap.projectId === currentProject?.id
    ? mindMap.value
    : null;
  const currentVideoSummary = videoSummary !== null && videoSummary.projectId === currentProject?.id
    ? videoSummary.value
    : null;

  const optionDisabled = (option: StudioOption) => {
    if (!option.available || !currentProject) return true;
    if (option.action === 'audio') return !speechSupported || isPreparingAudio;
    if (option.action === 'mindmap') return isBuildingMindMap || currentMindMap !== null;
    if (option.action === 'video') {
      return isPreparingVideo || currentVideoSummary !== null || hasNoSources;
    }
    return isGeneratingReport;
  };

  const optionLabel = (option: StudioOption) => {
    if (!option.available) return `${option.title} (${availabilityLabel})`;
    if (option.action === 'audio' && isSpeaking) return 'Stop audio summary';
    return option.title;
  };

  const optionIcon = (option: StudioOption) => {
    if (option.action === 'audio') {
      if (isPreparingAudio) return <Loader2 className="w-5 h-5 animate-spin" />;
      if (isSpeaking) return <Square className="w-5 h-5" />;
      return option.icon;
    }

    if (option.action === 'report' && isGeneratingReport) {
      return <Loader2 className="w-5 h-5 animate-spin" />;
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

    if (option.action === 'audio') {
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

    if (option.action === 'report' && isGeneratingReport) {
      return 'Generating report…';
    }

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
    }
  ];

  return (
    <aside
      aria-label="Studio"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-l border-[var(--border)] bg-[var(--card)] flex flex-col h-full"
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
        <div className="p-4 border-b border-[var(--border)]">
          <h2 className="pr-10 text-base font-medium">Studio</h2>
        </div>

        {/* Studio Options */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="space-y-3">
            {studioOptions.map((option) => {
              const hint = optionHint(option);
              const hintId = `${optionHintIdPrefix}-${option.id}-hint`;

              return (
                <button
                  key={option.id}
                  onClick={optionAction(option)}
                  disabled={optionDisabled(option)}
                  aria-label={optionLabel(option)}
                  aria-describedby={hintId}
                  title={hint}
                  className="w-full p-4 bg-[var(--secondary)] rounded-lg text-left group disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-[var(--card)] rounded-lg group-hover:bg-[var(--secondary)] transition-base">
                      {optionIcon(option)}
                    </div>
                    <h3 className="flex-1 text-sm font-medium">
                      {option.title}
                    </h3>
                  </div>
                  <span id={hintId} className="sr-only">{hint}</span>
                </button>
              );
            })}
          </div>

          {reportError && (
            <p role="alert" className="mt-3 text-xs text-[var(--error)]">
              {reportError}
            </p>
          )}

          {/* More Options */}
          <button
            disabled
            aria-label={`More options (${availabilityLabel})`}
            className="w-full mt-4 p-3 text-sm text-[var(--muted-foreground)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {/* The availability note lives in the accessible name only: English
                is long enough to wrap and crowd the bounded Studio track. */}
            <span className="truncate">More options</span>
            <ChevronDown className="w-4 h-4 shrink-0" />
          </button>

        </div>
      </div>

      {currentMindMap && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <MindMapDialog map={currentMindMap} onClose={() => setMindMap(null)} />
        </React.Suspense>
      )}

      {currentVideoSummary && (
        <React.Suspense fallback={<StudioDialogFallback />}>
          <VideoSummaryDialog
            summary={currentVideoSummary}
            onClose={() => setVideoSummary(null)}
          />
        </React.Suspense>
      )}
    </aside>
  );
}
