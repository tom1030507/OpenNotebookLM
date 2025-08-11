"use client";

import React, { useState } from 'react';
import { 
  Plus, 
  Search,
  FileText,
  Globe,
  Youtube,
  File,
  X
} from 'lucide-react';

interface Source {
  id: string;
  title: string;
  type: 'pdf' | 'website' | 'youtube' | 'text';
  description?: string;
  uploadedAt: Date;
}

export default function SourcesPanel() {
  const [sources, setSources] = useState<Source[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  const getSourceIcon = (type: Source['type']) => {
    switch (type) {
      case 'pdf':
        return <FileText className="w-4 h-4" />;
      case 'website':
        return <Globe className="w-4 h-4" />;
      case 'youtube':
        return <Youtube className="w-4 h-4" />;
      default:
        return <File className="w-4 h-4" />;
    }
  };

  return (
    <aside className="w-80 border-r border-[var(--border)] bg-[var(--sidebar-bg)] flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--sidebar-border)]">
        <h2 className="text-base font-medium mb-3">來源</h2>
        
        {/* Add Source Button */}
        <button className="w-full flex items-center justify-center gap-2 py-2 px-4 border border-[var(--border)] rounded-lg hover:bg-[var(--card)] transition-base">
          <Plus className="w-4 h-4" />
          <span className="text-sm">新增</span>
        </button>

        {/* Search */}
        <div className="mt-3 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            placeholder="搜索"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-3 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
          />
        </div>
      </div>

      {/* Sources List */}
      <div className="flex-1 overflow-y-auto p-4">
        {sources.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
              <FileText className="w-8 h-8 text-[var(--muted-foreground)]" />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              已儲存的來源會顯示在這裡
            </p>
            <p className="text-xs text-[var(--muted-foreground)] mt-2">
              點選上方的「新增來源」即可新增 PDF、網站、文字、影片或音訊檔案。
            </p>
            <p className="text-xs text-[var(--muted-foreground)] mt-1">
              你也可以直接拖曳 Google 雲端硬碟匯入檔案。
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {sources.map((source) => (
              <div
                key={source.id}
                className="p-3 bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer"
              >
                <div className="flex items-start gap-3">
                  <div className="p-2 bg-[var(--muted)] rounded">
                    {getSourceIcon(source.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium truncate">
                      {source.title}
                    </h3>
                    {source.description && (
                      <p className="text-xs text-[var(--muted-foreground)] mt-1 line-clamp-2">
                        {source.description}
                      </p>
                    )}
                  </div>
                  <button className="p-1 hover:bg-[var(--muted)] rounded transition-base">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
