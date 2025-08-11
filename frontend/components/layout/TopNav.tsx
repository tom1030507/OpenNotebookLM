"use client";

import React, { useState } from 'react';
import { 
  FileText, 
  Lock,
  Settings,
  Grid3X3,
  ChevronDown,
  Download,
  Moon,
  Sun
} from 'lucide-react';
import ExportDialog from '../ExportDialog';
import useStore from '@/store/useStore';

interface TopNavProps {
  notebookTitle?: string;
}

export default function TopNav({ notebookTitle = "OpenNotebookLM" }: TopNavProps) {
  const [showExport, setShowExport] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  
  const { currentProject, currentConversation } = useStore();
  
  return (
    <>
      <header className="h-14 border-b border-[var(--border)] bg-[var(--card)] flex items-center px-4 gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-purple-700 flex items-center justify-center">
            <FileText className="w-4 h-4 text-white" />
          </div>
        </div>

        {/* Notebook Title */}
        <div className="flex items-center gap-2 flex-1">
          <h1 className="text-base font-medium text-[var(--foreground)]">
            {currentProject ? currentProject.name : notebookTitle}
          </h1>
          {currentConversation && (
            <>
              <ChevronDown className="w-4 h-4 text-[var(--muted-foreground)] rotate-[-90deg]" />
              <span className="text-sm text-[var(--muted-foreground)]">
                {currentConversation.title}
              </span>
            </>
          )}
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2">
          {/* Export Button */}
          {(currentProject || currentConversation) && (
            <button
              onClick={() => setShowExport(true)}
              className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
              title="Export"
            >
              <Download className="w-4 h-4" />
            </button>
          )}
          
          {/* Theme Toggle */}
          <button 
            onClick={() => setIsDarkMode(!isDarkMode)}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
            aria-label="Toggle theme"
          >
            {isDarkMode ? (
              <Sun className="w-4 h-4" />
            ) : (
              <Moon className="w-4 h-4" />
            )}
          </button>
          
          {/* Share Button */}
          <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
            <Lock className="w-4 h-4" />
            <span>Share</span>
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
      
      {/* Export Dialog */}
      {showExport && (currentConversation || currentProject) && (
        <ExportDialog
          type={currentConversation ? 'conversation' : 'project'}
          id={currentConversation?.id || currentProject?.id || ''}
          name={currentConversation?.title || currentProject?.name || ''}
          onClose={() => setShowExport(false)}
        />
      )}
    </>
  );
}
