"use client";

import React, { useState } from 'react';
import { 
  FileText, 
  Lock,
  Settings as SettingsIcon,
  Grid3X3,
  ChevronDown,
  Download,
  Moon,
  Sun,
  User,
  FolderPlus,
  LogOut,
  Bell,
  HelpCircle,
  Search
} from 'lucide-react';
import ExportDialog from '../ExportDialog';
import ProjectDialog from '../ProjectDialog';
import Settings from '../Settings';
import useStore from '@/store/useStore';

interface TopNavProps {
  notebookTitle?: string;
}

export default function TopNav({ notebookTitle = "OpenNotebookLM" }: TopNavProps) {
  const [showExport, setShowExport] = useState(false);
  const [showProjectDialog, setShowProjectDialog] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
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
          {/* New Project Button */}
          <button
            onClick={() => setShowProjectDialog(true)}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
            title="New Project"
          >
            <FolderPlus className="w-4 h-4" />
          </button>
          
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
          
          {/* Notifications */}
          <button className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
            <Bell className="w-4 h-4" />
          </button>
          
          {/* Help */}
          <button className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base">
            <HelpCircle className="w-4 h-4" />
          </button>

          {/* Settings */}
          <button 
            onClick={() => setShowSettings(true)}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <SettingsIcon className="w-4 h-4" />
          </button>

          {/* User Menu */}
          <div className="relative">
            <button 
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-medium hover:opacity-90 transition-base"
            >
              <User className="w-5 h-5" />
            </button>
            
            {showUserMenu && (
              <div className="absolute right-0 mt-2 w-48 bg-[var(--card)] rounded-lg shadow-lg border border-[var(--border)] py-2 z-50">
                <div className="px-4 py-2 border-b border-[var(--border)]">
                  <p className="text-sm font-medium">User</p>
                  <p className="text-xs text-[var(--muted-foreground)]">user@example.com</p>
                </div>
                <button className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base">
                  Profile
                </button>
                <button 
                  onClick={() => {
                    setShowUserMenu(false);
                    setShowSettings(true);
                  }}
                  className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base"
                >
                  Settings
                </button>
                <div className="border-t border-[var(--border)] mt-2 pt-2">
                  <button className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base flex items-center gap-2">
                    <LogOut className="w-4 h-4" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>
      
      {/* Dialogs */}
      {showExport && (currentConversation || currentProject) && (
        <ExportDialog
          type={currentConversation ? 'conversation' : 'project'}
          id={currentConversation?.id || currentProject?.id || ''}
          name={currentConversation?.title || currentProject?.name || ''}
          onClose={() => setShowExport(false)}
        />
      )}
      
      <ProjectDialog 
        isOpen={showProjectDialog} 
        onClose={() => setShowProjectDialog(false)}
        onSuccess={() => setShowProjectDialog(false)}
      />
      
      <Settings 
        isOpen={showSettings} 
        onClose={() => setShowSettings(false)} 
      />
    </>
  );
}
