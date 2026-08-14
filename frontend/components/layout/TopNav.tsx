"use client";

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  FileText,
  Settings as SettingsIcon,
  ChevronDown,
  Download,
  Moon,
  MoreHorizontal,
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
import useDialogFocus from '@/hooks/useDialogFocus';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { applyThemePreference, initializeTheme, type Theme } from '@/lib/theme';
import {
  COMPACT_TOP_NAV_MEDIA_QUERY,
  TOP_NAV_ACTIONS,
  getTopNavActionLayout,
  type TopNavActionId,
} from './topNavContract';

interface TopNavProps {
  notebookTitle?: string;
}

interface TopNavAction {
  /** Visible text in the overflow menu. */
  label: string;
  /** Accessible name, when it has to carry more than the label does. */
  accessibleName?: string;
  icon: React.ReactNode;
  onSelect: () => void;
  isBadged?: boolean;
}

export default function TopNav({ notebookTitle = "OpenNotebookLM" }: TopNavProps) {
  const [showExport, setShowExport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const moreActionsRef = useRef<HTMLDivElement>(null);
  const firstOverflowActionRef = useRef<HTMLButtonElement>(null);

  const { currentProject, currentConversation, documents } = useStore();
  const router = useRouter();
  const { openProjectDialog } = useProjectDialog();
  const isCompact = useMediaQuery(COMPACT_TOP_NAV_MEDIA_QUERY);

  useDialogFocus({
    isOpen: showMoreActions,
    onClose: () => setShowMoreActions(false),
    dialogRef: moreActionsRef,
    initialFocusRef: firstOverflowActionRef,
  });

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

  // The toggle is an explicit choice, so it records light or dark rather than
  // leaving the theme following the system. Settings reads the same record.
  const toggleTheme = () => {
    const nextTheme: Theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';

    applyThemePreference(nextTheme);
  };

  const canExport = Boolean(currentProject || currentConversation);
  const actions: Record<TopNavActionId, TopNavAction> = {
    'new-project': {
      label: 'New Project',
      icon: <FolderPlus className="w-4 h-4" />,
      onSelect: openProjectDialog,
    },
    export: {
      label: 'Export',
      icon: <Download className="w-4 h-4" />,
      onSelect: () => setShowExport(true),
    },
    theme: {
      label: 'Toggle theme',
      icon: (
        <>
          <Sun data-theme-icon="sun" className="theme-icon--sun w-4 h-4" />
          <Moon data-theme-icon="moon" className="theme-icon--moon w-4 h-4" />
        </>
      ),
      onSelect: toggleTheme,
    },
    notifications: {
      label: 'Notifications',
      accessibleName: notificationCount > 0 ? `Notifications (${notificationCount})` : 'Notifications',
      icon: <Bell className="w-4 h-4" />,
      onSelect: () => setShowNotifications(true),
      isBadged: true,
    },
    help: {
      label: 'Help',
      icon: <HelpCircle className="w-4 h-4" />,
      onSelect: () => setShowHelp(true),
    },
    settings: {
      label: 'Settings',
      icon: <SettingsIcon className="w-4 h-4" />,
      onSelect: () => setShowSettings(true),
    },
  };

  const { inlineActionIds, overflowActionIds } = getTopNavActionLayout(
    TOP_NAV_ACTIONS.filter((id) => id !== 'export' || canExport),
    isCompact,
  );
  // Compact targets are 44px squares; the desktop bar keeps its original padding.
  const actionButtonClassName = `${
    isCompact ? 'flex h-11 w-11 items-center justify-center' : 'p-2'
  } text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base`;
  const menuPanelClassName = 'absolute right-0 mt-2 bg-[var(--card)] rounded-lg shadow-lg border border-[var(--border)] py-2 z-50';
  // Menu rows only need the 44px floor where fingers, not pointers, use them.
  const menuItemClassName = `w-full ${isCompact ? 'min-h-11 ' : ''}text-left px-4 py-2 text-sm hover:bg-[var(--muted)] transition-base`;

  const openUserMenu = () => {
    setShowMoreActions(false);
    setShowUserMenu(!showUserMenu);
  };

  const openMoreActions = () => {
    setShowUserMenu(false);
    setShowMoreActions(!showMoreActions);
  };

  const runOverflowAction = (action: TopNavAction) => {
    setShowMoreActions(false);
    action.onSelect();
  };

  return (
    <>
      <header className="h-14 border-b border-[var(--border)] bg-[var(--card)] flex items-center px-4 gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-purple-700 flex items-center justify-center">
            <FileText className="w-4 h-4 text-white" />
          </div>
        </div>

        {/* Notebook Title — truncates so the controls keep their tap targets */}
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <h1 className="text-base font-medium text-[var(--foreground)] truncate">
            {currentProject ? currentProject.name : notebookTitle}
          </h1>
          {currentConversation && (
            <>
              <ChevronDown className="w-4 h-4 shrink-0 text-[var(--muted-foreground)] rotate-[-90deg]" />
              <span className="text-sm text-[var(--muted-foreground)] truncate">
                {currentConversation.title}
              </span>
            </>
          )}
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {inlineActionIds.map((id) => {
            const action = actions[id];

            return (
              <button
                key={id}
                type="button"
                onClick={action.onSelect}
                aria-label={action.accessibleName ?? action.label}
                title={action.label}
                className={action.isBadged ? `relative ${actionButtonClassName}` : actionButtonClassName}
              >
                {action.icon}
                {id === 'notifications' && notificationCount > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-[var(--error)]" />
                )}
              </button>
            );
          })}

          {/* Overflow menu for the actions a phone-width bar cannot show */}
          {overflowActionIds.length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={openMoreActions}
                aria-label="More actions"
                title="More actions"
                aria-haspopup="menu"
                aria-expanded={showMoreActions}
                className="flex h-11 w-11 items-center justify-center text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
              >
                <MoreHorizontal className="w-5 h-5" />
              </button>

              {showMoreActions && (
                <div
                  ref={moreActionsRef}
                  role="menu"
                  aria-label="More actions"
                  className={`w-56 ${menuPanelClassName}`}
                >
                  {overflowActionIds.map((id, index) => {
                    const action = actions[id];

                    return (
                      <button
                        key={id}
                        ref={index === 0 ? firstOverflowActionRef : undefined}
                        type="button"
                        onClick={() => runOverflowAction(action)}
                        aria-label={action.accessibleName ?? action.label}
                        title={action.label}
                        className={`${menuItemClassName} flex items-center gap-3`}
                      >
                        <span className="flex shrink-0 items-center text-[var(--muted-foreground)]">
                          {action.icon}
                        </span>
                        <span>{action.label}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* User Menu */}
          <div className="relative">
            <button
              onClick={openUserMenu}
              aria-label={'User menu'}
              title={'User menu'}
              aria-haspopup="menu"
              aria-expanded={showUserMenu}
              className={`${isCompact ? 'h-11 w-11' : 'w-8 h-8'} rounded-full bg-purple-600 text-white flex items-center justify-center text-sm font-medium hover:opacity-90 transition-base`}
            >
              <User className="w-5 h-5" />
            </button>

            {showUserMenu && (
              <div
                role="menu"
                aria-label="User menu"
                className={`w-48 ${menuPanelClassName}`}
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
                  className={menuItemClassName}
                >
                  Profile
                </button>
                <button
                  onClick={() => {
                    setShowUserMenu(false);
                    setShowSettings(true);
                  }}
                  className={menuItemClassName}
                >
                  Settings
                </button>
                <div className="border-t border-[var(--border)] mt-2 pt-2">
                  <button
                    onClick={signOut}
                    className={`${menuItemClassName} flex items-center gap-2`}
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
