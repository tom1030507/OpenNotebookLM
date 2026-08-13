'use client';

import React, { useState } from 'react';
import { 
  Mic,
  Video,
  FileText,
  Brain,
  ChevronDown,
  PanelRightClose,
  PanelRightOpen,
  Loader2,
} from 'lucide-react';
import useStore from '@/store/useStore';
import api from '@/lib/api';

interface StudioOption {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  /** Outputs with no backend endpoint stay unavailable. */
  available?: boolean;
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
  const studioOptions: StudioOption[] = [
    {
      id: 'audio',
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
                onClick={option.available ? generateReport : undefined}
                disabled={!option.available || !currentProject || isGeneratingReport}
                aria-label={option.available
                  ? option.title
                  : `${option.title} (${availabilityLabel})`}
                className="w-full p-4 bg-[var(--secondary)] rounded-lg text-left group disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-[var(--card)] rounded-lg group-hover:bg-[var(--secondary)] transition-base">
                    {option.available && isGeneratingReport
                      ? <Loader2 className="w-5 h-5 animate-spin" />
                      : option.icon}
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-medium">
                      {option.title}
                    </h3>
                    <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                      {option.available
                        ? (currentProject ? 'Summarise this project' : 'Select a project first')
                        : availabilityLabel}
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
                  Studio is coming soon
                </h4>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Reports are available now. Audio, video and mind maps are still
                  in preparation.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
