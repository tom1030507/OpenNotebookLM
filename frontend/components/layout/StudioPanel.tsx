'use client';

import React from 'react';
import { 
  Mic,
  Video,
  FileText,
  Brain,
  ChevronDown,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react';

interface StudioOption {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}

interface StudioPanelProps {
  isCollapsed?: boolean;
  onCollapsedChange?: (isCollapsed: boolean) => void;
}

export default function StudioPanel({
  isCollapsed = false,
  onCollapsedChange,
}: StudioPanelProps) {
  const studioOptions: StudioOption[] = [
    {
      id: 'audio',
      title: '音頻摘要',
      description: '',
      icon: <Mic className="w-5 h-5" />
    },
    {
      id: 'video', 
      title: '影片摘要',
      description: '',
      icon: <Video className="w-5 h-5" />
    },
    {
      id: 'mindmap',
      title: '心智圖',
      description: '',
      icon: <Brain className="w-5 h-5" />
    },
    {
      id: 'report',
      title: '報告',
      description: '',
      icon: <FileText className="w-5 h-5" />
    }
  ];

  return (
    <aside
      aria-label="工作室"
      data-panel-state={isCollapsed ? 'collapsed' : 'expanded'}
      className="relative w-full min-w-0 overflow-hidden border-l border-[var(--border)] bg-[var(--card)] flex flex-col h-full"
    >
      <button
        type="button"
        onClick={() => onCollapsedChange?.(!isCollapsed)}
        aria-controls="studio-panel-content"
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? '展開工作室' : '收合工作室'}
        title={isCollapsed ? '展開工作室' : '收合工作室'}
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
        aria-label="工作室面板內容"
        hidden={isCollapsed}
        className="min-h-0 flex-1 flex flex-col"
      >
        {/* Header */}
        <div className="p-4 border-b border-[var(--border)]">
          <h2 className="pr-10 text-base font-medium">工作室</h2>
        </div>

        {/* Studio Options */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="space-y-3">
            {studioOptions.map((option) => (
              <button
                key={option.id}
                className="w-full p-4 bg-[var(--secondary)] rounded-lg hover:bg-[var(--muted)] transition-base text-left group"
              >
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-[var(--card)] rounded-lg group-hover:bg-[var(--secondary)] transition-base">
                    {option.icon}
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-medium">
                      {option.title}
                    </h3>
                    {option.description && (
                      <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                        {option.description}
                      </p>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* More Options */}
          <button className="w-full mt-4 p-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-lg transition-base flex items-center justify-center gap-2">
            <span>更多選項</span>
            <ChevronDown className="w-4 h-4" />
          </button>

          {/* Tip Section */}
          <div className="mt-6 p-4 bg-[var(--secondary)] rounded-lg">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-[var(--accent)] flex items-center justify-center flex-shrink-0">
                <span className="text-white text-xs">💡</span>
              </div>
              <div>
                <h4 className="text-sm font-medium mb-1">
                  工作室輸出內容儲存在這裡。
                </h4>
                <p className="text-xs text-[var(--muted-foreground)]">
                  加入來源後，點選即可新增語音摘要、研讀指南、心智圖等內容！
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
