"use client";

import React from 'react';
import { 
  FileText, 
  Lock,
  Settings,
  Grid3X3,
  ChevronDown
} from 'lucide-react';

interface TopNavProps {
  notebookTitle?: string;
}

export default function TopNav({ notebookTitle = "Untitled notebook" }: TopNavProps) {
  return (
    <header className="h-14 border-b border-[var(--border)] bg-[var(--card)] flex items-center px-4 gap-4">
      {/* Logo */}
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-purple-700 flex items-center justify-center">
          <FileText className="w-4 h-4 text-white" />
        </div>
      </div>

      {/* Notebook Title */}
      <div className="flex items-center gap-2 flex-1">
        <h1 className="text-base font-normal text-[var(--foreground)]">
          {notebookTitle}
        </h1>
      </div>

      {/* Right Actions */}
      <div className="flex items-center gap-2">
        {/* Share Button */}
        <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
          <Lock className="w-4 h-4" />
          <span>共用</span>
        </button>

        {/* Settings */}
        <button className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
          <Settings className="w-4 h-4" />
        </button>

        {/* Grid Menu */}
        <button className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
          <Grid3X3 className="w-4 h-4" />
        </button>

        {/* User Avatar */}
        <button className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-medium">
          U
        </button>
      </div>
    </header>
  );
}
