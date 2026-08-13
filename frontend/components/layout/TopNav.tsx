"use client";

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { 
  FileText, 
  Settings as SettingsIcon,
  ChevronDown,
  Download,
  Moon,
  Sun,
  User,
  FolderPlus,
  LogOut,
  Bell,
  HelpCircle
} from 'lucide-react';
import ExportDialog from '../ExportDialog';
import TopNavInfoDialog from './TopNavInfoDialog';
import { useProjectDialog } from '../ProjectDialogProvider';
import Settings from '../Settings';
import useStore from '@/store/useStore';
import { applyTheme, initializeTheme, THEME_STORAGE_KEY, type Theme } from '@/lib/theme';

interface TopNavProps {
  notebookTitle?: string;
}

export default function TopNav({ notebookTitle = "OpenNotebookLM" }: TopNavProps) {
  const [showExport, setShowExport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  
  const { currentProject, currentConversation, documents } = useStore();
  const router = useRouter();
  const { openProjectDialog } = useProjectDialog();

  useEffect(() => {
    initializeTheme();
  }, []);

  const readAccount = () => {
    try {
      const raw = window.localStorage.getItem('user');
      const parsed = raw ? JSON.parse(raw) as { username?: string; email?: string } : null;
      return {
        username: parsed?.username || 'Demo user',
        email: parsed?.email || 'demo@example.com',
      };
    } catch {
      return { username: 'Demo user', email: 'demo@example.com' };
    }
  };

  const signOut = () => {
    for (const key of ['access_token', 'auth_token', 'user']) {
      try {
        window.localStorage.removeItem(key);
      } catch {
        // Navigation still returns the user to the login page.
      }
    }

    setShowUserMenu(false);
    router.push('/login');
  };

  // Documents are the only asynchronous work the workspace runs today, so their
  // status is what there is to notify about.
  const pendingDocuments = documents.filter(
    (document) => document.status === 'queued' || document.status === 'processing',
  );
  const failedDocuments = documents.filter((document) => document.status === 'error');
  const notificationCount = pendingDocuments.length + failedDocuments.length;

  const toggleTheme = () => {
    const nextTheme: Theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';

    applyTheme(nextTheme, document.documentElement);

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // The current-session choice still applies if persistence is unavailable.
    }
  };

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
            onClick={openProjectDialog}
            aria-label={'New Project'}
            title={'New Project'}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <FolderPlus className="w-4 h-4" />
          </button>
          
          {/* Export Button */}
          {(currentProject || currentConversation) && (
            <button
              onClick={() => setShowExport(true)}
              className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
              aria-label={'Export'}
              title={'Export'}
            >
              <Download className="w-4 h-4" />
            </button>
          )}
          
          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
            aria-label={'Toggle theme'}
            title={'Toggle theme'}
          >
            <Sun data-theme-icon="sun" className="theme-icon--sun w-4 h-4" />
            <Moon data-theme-icon="moon" className="theme-icon--moon w-4 h-4" />
          </button>
          
          {/* Notifications */}
          <button
            onClick={() => setShowNotifications(true)}
            aria-label={notificationCount > 0 ? `Notifications (${notificationCount})` : 'Notifications'}
            title="Notifications"
            className="relative p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <Bell className="w-4 h-4" />
            {notificationCount > 0 && (
              <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-[var(--error)]" />
            )}
          </button>
          
          {/* Help */}
          <button
            onClick={() => setShowHelp(true)}
            aria-label="Help"
            title="Help"
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <HelpCircle className="w-4 h-4" />
          </button>

          {/* Settings */}
          <button 
            onClick={() => setShowSettings(true)}
            aria-label={'Settings'}
            title={'Settings'}
            className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <SettingsIcon className="w-4 h-4" />
          </button>

          {/* User Menu */}
          <div className="relative">
            <button 
              onClick={() => setShowUserMenu(!showUserMenu)}
              aria-label={'User menu'}
              title={'User menu'}
              aria-haspopup="menu"
              aria-expanded={showUserMenu}
              className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-medium hover:opacity-90 transition-base"
            >
              <User className="w-5 h-5" />
            </button>
            
            {showUserMenu && (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-48 bg-[var(--card)] rounded-lg shadow-lg border border-[var(--border)] py-2 z-50"
              >
                <div className="px-4 py-2 border-b border-[var(--border)]">
                  <p className="text-sm font-medium">{readAccount().username}</p>
                  <p className="text-xs text-[var(--muted-foreground)]">{readAccount().email}</p>
                </div>
                <button
                  onClick={() => {
                    setShowUserMenu(false);
                    setShowProfile(true);
                  }}
                  className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base"
                >
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
                  <button
                    onClick={signOut}
                    className="w-full text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base flex items-center gap-2"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>Sign out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>
      
      {showProfile && (
        <TopNavInfoDialog title="Profile" onClose={() => setShowProfile(false)}>
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs text-[var(--muted-foreground)]">Username</dt>
              <dd className="font-medium">{readAccount().username}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--muted-foreground)]">Email</dt>
              <dd className="font-medium">{readAccount().email}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-[var(--muted-foreground)]">
            This workspace runs in demo mode. Account details come from the browser session.
          </p>
        </TopNavInfoDialog>
      )}

      {showHelp && (
        <TopNavInfoDialog title="Help" onClose={() => setShowHelp(false)}>
          <ol className="space-y-2 text-sm list-decimal list-inside">
            <li>Create a project to hold related material.</li>
            <li>Add sources: upload a PDF, or paste a web page or YouTube link.</li>
            <li>Wait for a source to report Ready, then ask a question in the composer.</li>
            <li>Export a conversation or a whole project from the toolbar.</li>
          </ol>
          <p className="mt-4 text-xs text-[var(--muted-foreground)]">
            Studio outputs (audio, video, mind maps) are not available yet.
          </p>
          <a
            href="https://github.com/tom1030507/OpenNotebookLM"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-block text-sm text-[var(--primary)] hover:underline"
          >
            Documentation on GitHub
          </a>
        </TopNavInfoDialog>
      )}

      {showNotifications && (
        <TopNavInfoDialog title="Notifications" onClose={() => setShowNotifications(false)}>
          {notificationCount === 0 ? (
            <p className="text-sm text-[var(--muted-foreground)]">
              No notifications. Source processing updates appear here.
            </p>
          ) : (
            <ul className="space-y-3">
              {failedDocuments.map((document) => (
                <li key={document.id} className="text-sm">
                  <p className="font-medium">{document.name}</p>
                  <p className="text-xs text-[var(--error)]">
                    Failed to process{document.error_message ? `: ${document.error_message}` : ''}
                  </p>
                </li>
              ))}
              {pendingDocuments.map((document) => (
                <li key={document.id} className="text-sm">
                  <p className="font-medium">{document.name}</p>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    Currently {document.status}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </TopNavInfoDialog>
      )}

      {/* Dialogs */}
      {showExport && (currentConversation || currentProject) && (
        <ExportDialog
          type={currentConversation ? 'conversation' : 'project'}
          id={currentConversation?.id || currentProject?.id || ''}
          name={currentConversation?.title || currentProject?.name || ''}
          onClose={() => setShowExport(false)}
        />
      )}
      
      <Settings 
        isOpen={showSettings} 
        onClose={() => setShowSettings(false)} 
      />
    </>
  );
}
