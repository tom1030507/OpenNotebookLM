'use client';

import React, { useEffect, useState } from 'react';
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
import { isSpeechSupported, speakText, stopSpeaking, summaryToSpeech } from '@/lib/speech';

interface StudioOption {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  /** Outputs with no backend endpoint stay unavailable. */
  available?: boolean;
  /** Distinguishes the live actions from one another. */
  action?: 'report' | 'audio';
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
  const currentProject = useStore((state) => state.currentProject);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [reportError, setReportError] = useState('');
  const [isPreparingAudio, setIsPreparingAudio] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(true);

  // Speech support can only be read in the browser, so check after mount to
  // keep the server-rendered markup stable.
  useEffect(() => {
    setSpeechSupported(isSpeechSupported());
    return () => stopSpeaking();
  }, []);

  const playAudioSummary = async () => {
    if (!currentProject) return;

    setIsPreparingAudio(true);
    setReportError('');

    try {
      const spoken = summaryToSpeech(await api.fetchProjectSummaryText(currentProject.id));

      setIsPreparingAudio(false);
      setIsSpeaking(true);
      await speakText(spoken);
    } catch {
      setReportError('The audio summary could not be read out. Please try again.');
    } finally {
      setIsPreparingAudio(false);
      setIsSpeaking(false);
    }
  };

  const stopAudioSummary = () => {
    stopSpeaking();
    setIsSpeaking(false);
  };

  // The backend exposes a project summary, so Report is a real action. Audio,
  // video and mind maps have no endpoint yet, so they stay unavailable.
  const generateReport = async () => {
    if (!currentProject) return;

    setIsGeneratingReport(true);
    setReportError('');

    try {
      const blob = await api.exportProjectSummary(currentProject.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${currentProject.name} report.md`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      setReportError('The report could not be generated. Please try again.');
    } finally {
      setIsGeneratingReport(false);
    }
  };
  const optionAction = (option: StudioOption) => {
    if (option.action === 'report') return generateReport;
    if (option.action === 'audio') return isSpeaking ? stopAudioSummary : playAudioSummary;
    return undefined;
  };

  const optionDisabled = (option: StudioOption) => {
    if (!option.available || !currentProject) return true;
    if (option.action === 'audio') return !speechSupported || isPreparingAudio;
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

    return 'Summarise this project';
  };

  const studioOptions: StudioOption[] = [
    {
      id: 'audio',
      available: true,
      action: 'audio',
      title: 'Audio summary',
      description: '',
      icon: <Mic className="w-5 h-5" />
    },
    {
      id: 'video', 
      title: 'Video summary',
      description: '',
      icon: <Video className="w-5 h-5" />
    },
    {
      id: 'mindmap',
      title: 'Mind map',
      description: '',
      icon: <Brain className="w-5 h-5" />
    },
    {
      id: 'report',
      available: true,
      action: 'report',
      title: 'Report',
      description: '',
      icon: <FileText className="w-5 h-5" />
    }
  ];

  return (
    <aside
      aria-label="Studio"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-l border-[var(--border)] bg-[var(--card)] flex flex-col h-full"
    >
      <button
        type="button"
        onClick={() => onCollapsedChange?.(!isCollapsed)}
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
            {studioOptions.map((option) => (
              <button
                key={option.id}
                onClick={optionAction(option)}
                disabled={optionDisabled(option)}
                aria-label={optionLabel(option)}
                className="w-full p-4 bg-[var(--secondary)] rounded-lg text-left group disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-[var(--card)] rounded-lg group-hover:bg-[var(--secondary)] transition-base">
                    {optionIcon(option)}
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-medium">
                      {option.title}
                    </h3>
                    <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                      {optionHint(option)}
                    </p>
                  </div>
                </div>
              </button>
            ))}
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

          {/* Tip Section */}
          <div className="mt-6 p-4 bg-[var(--secondary)] rounded-lg">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-[var(--accent)] flex items-center justify-center flex-shrink-0">
                <span className="text-white text-xs">💡</span>
              </div>
              <div>
                <h4 className="text-sm font-medium mb-1">
                  Studio outputs
                </h4>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Audio summaries and reports are available now. Video and mind
                  maps are still in preparation.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
