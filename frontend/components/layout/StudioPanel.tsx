"use client";

import React from 'react';
import { 
  Mic,
  Video,
  FileText,
  Brain,
  ChevronDown
} from 'lucide-react';

interface StudioOption {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}

export default function StudioPanel() {
  const availabilityLabel = '即將推出';
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
    <aside className="w-80 border-l border-[var(--border)] bg-[var(--card)] flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)]">
        <h2 className="text-base font-medium">工作室</h2>
      </div>

      {/* Studio Options */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="space-y-3">
          {studioOptions.map((option) => (
            <button
              key={option.id}
              disabled
              aria-label={`${option.title}${availabilityLabel}`}
              className="w-full p-4 bg-[var(--secondary)] rounded-lg text-left group disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-[var(--card)] rounded-lg group-hover:bg-[var(--secondary)] transition-base">
                  {option.icon}
                </div>
                <div className="flex-1">
                  <h3 className="text-sm font-medium">
                    {option.title}
                  </h3>
                  <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
                    {availabilityLabel}
                  </p>
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
        <button
          disabled
          aria-label={`更多選項${availabilityLabel}`}
          className="w-full mt-4 p-3 text-sm text-[var(--muted-foreground)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          <span>更多選項</span>
          <ChevronDown className="w-4 h-4" />
          <span className="text-xs">{availabilityLabel}</span>
        </button>

        {/* Tip Section */}
        <div className="mt-6 p-4 bg-[var(--secondary)] rounded-lg">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-[var(--accent)] flex items-center justify-center flex-shrink-0">
              <span className="text-white text-xs">💡</span>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-1">
                工作室功能即將推出
              </h4>
              <p className="text-xs text-[var(--muted-foreground)]">
                音訊、影片、心智圖與報告功能仍在準備中。
              </p>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
