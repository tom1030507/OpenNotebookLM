'use client';

import React, { useId, useRef, useState } from 'react';
import {
  X,
  Settings as SettingsIcon,
  Moon,
  Sun,
  Key,
  Database,
  Bell,
  Shield,
  HelpCircle,
  ChevronRight,
  Save,
  Loader2
} from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api from '@/lib/api';
import useStore from '@/store/useStore';
import {
  applyThemePreference,
  readThemePreference,
  type ThemePreference,
} from '@/lib/theme';

interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = 'general' | 'api' | 'data' | 'notifications' | 'security' | 'about';

const REPOSITORY_URL = 'https://github.com/tom1030507/OpenNotebookLM';
// The Studio panel marks its unfinished outputs with the same words.
const availabilityLabel = 'coming soon';

export default function Settings({ isOpen, onClose }: SettingsProps) {
  const storedNotifyOnComplete = useStore((state) => state.notifyOnProcessingComplete);
  const setStoredNotifyOnComplete = useStore((state) => state.setNotifyOnProcessingComplete);

  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [theme, setTheme] = useState<ThemePreference>(
    () => (isOpen ? readThemePreference() : 'system'),
  );
  const [notifyOnComplete, setNotifyOnComplete] = useState(storedNotifyOnComplete);
  const [wasOpen, setWasOpen] = useState(isOpen);
  const [isSaving, setIsSaving] = useState(false);
  const [isClearingCache, setIsClearingCache] = useState(false);
  const [cacheResult, setCacheResult] = useState('');
  const [cacheError, setCacheError] = useState('');
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const languageSelectId = useId();
  const languageHintId = useId();
  const autoSaveHintId = useId();
  const modelSelectId = useId();
  const apiKeyId = useId();
  const apiKeyHintId = useId();
  const endpointId = useId();
  const endpointHintId = useId();

  useDialogFocus({
    isOpen,
    onClose,
    dismissible: !isSaving,
    dialogRef,
    initialFocusRef: closeButtonRef,
  });

  // Seed the controls from the preferences in force every time the dialog
  // opens, so reopening shows what was saved rather than the defaults.
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);

    if (isOpen) {
      setTheme(readThemePreference());
      setNotifyOnComplete(storedNotifyOnComplete);
      setCacheResult('');
      setCacheError('');
    }
  }

  // Both writes are synchronous, but the dialog awaits the commit so it cannot
  // be dismissed part-way through one.
  const savePreferences = async () => {
    applyThemePreference(theme);
    setStoredNotifyOnComplete(notifyOnComplete);
  };

  const handleSave = async () => {
    setIsSaving(true);

    try {
      await savePreferences();
    } finally {
      setIsSaving(false);
    }

    onClose();
  };

  const clearCache = async () => {
    setIsClearingCache(true);
    setCacheResult('');
    setCacheError('');

    try {
      const cleared = await api.clearCache();
      setCacheResult(cleared < 0
        // A flushed Redis database reports no count.
        ? 'Server cache cleared.'
        : `Server cache cleared: ${cleared} cached ${cleared === 1 ? 'entry' : 'entries'} dropped.`);
    } catch {
      setCacheError('The cache could not be cleared. Please try again.');
    } finally {
      setIsClearingCache(false);
    }
  };

  if (!isOpen) return null;

  const tabs = [
    { id: 'general', label: 'General', icon: SettingsIcon },
    { id: 'api', label: 'API Keys', icon: Key },
    { id: 'data', label: 'Data & Storage', icon: Database },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'about', label: 'About', icon: HelpCircle },
  ];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--background)] rounded-lg w-full max-w-4xl max-h-[80vh] flex overflow-hidden"
      >
        {/* Sidebar */}
        <div className="w-64 border-r border-[var(--border)] bg-[var(--sidebar-bg)]">
          <div className="p-6 border-b border-[var(--border)]">
            <h2 id={titleId} className="text-lg font-semibold">Settings</h2>
          </div>
          <nav className="p-4">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as SettingsTab)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-base ${
                    activeTab === tab.id
                      ? 'bg-[var(--primary)] bg-opacity-10 text-[var(--primary)]'
                      : 'hover:bg-[var(--muted)]'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="text-sm font-medium">{tab.label}</span>
                  {activeTab === tab.id && (
                    <ChevronRight className="w-4 h-4 ml-auto" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Content */}
        <div className="flex-1 flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-[var(--border)]">
            <h3 className="text-base font-medium">
              {tabs.find(t => t.id === activeTab)?.label}
            </h3>
            <button
              ref={closeButtonRef}
              onClick={onClose}
              type="button"
              aria-label={'Close settings dialog'}
              title={'Close settings dialog'}
              disabled={isSaving}
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Settings Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === 'general' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">Appearance</h4>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm mb-2">Theme</label>
                      <div className="flex gap-2">
                        {[
                          { value: 'light', icon: Sun, label: 'Light' },
                          { value: 'dark', icon: Moon, label: 'Dark' },
                          { value: 'system', icon: SettingsIcon, label: 'System' },
                        ].map((option) => {
                          const Icon = option.icon;
                          const isSelected = theme === option.value;
                          return (
                            <button
                              key={option.value}
                              type="button"
                              aria-pressed={isSelected}
                              onClick={() => setTheme(option.value as ThemePreference)}
                              className={`flex items-center gap-2 px-4 py-2 rounded-lg border transition-base ${
                                isSelected
                                  ? 'border-[var(--primary)] bg-[var(--primary)] bg-opacity-10'
                                  : 'border-[var(--border)] hover:bg-[var(--muted)]'
                              }`}
                            >
                              <Icon className="w-4 h-4" />
                              <span className="text-sm">{option.label}</span>
                            </button>
                          );
                        })}
                      </div>
                      <p className="text-xs text-[var(--muted-foreground)] mt-2">
                        System follows your operating system. The toolbar toggle
                        changes the same setting.
                      </p>
                    </div>

                    <div>
                      <label htmlFor={languageSelectId} className="block text-sm mb-2">Language</label>
                      <select
                        id={languageSelectId}
                        aria-describedby={languageHintId}
                        disabled
                        defaultValue="en"
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      >
                        <option value="en">English</option>
                      </select>
                      <p id={languageHintId} className="text-xs text-[var(--muted-foreground)] mt-2">
                        The interface is English only ({availabilityLabel}).
                      </p>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">Behavior</h4>
                  <div className="space-y-3">
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked
                        readOnly
                        disabled
                        aria-describedby={autoSaveHintId}
                        className="w-4 h-4 mt-0.5 rounded border-[var(--border)]"
                      />
                      <div>
                        <p className="text-sm">Auto-save conversations</p>
                        <p id={autoSaveHintId} className="text-xs text-[var(--muted-foreground)]">
                          Always on: every question and answer is stored with its
                          conversation on the server, so this cannot be turned off.
                        </p>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'api' && (
              <div className="space-y-6">
                <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                  <p className="text-sm mb-2">Model access is configured on the server.</p>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    The backend reads its model settings from its own environment
                    (LLM_MODE, OPENAI_API_KEY). The fields below are not connected
                    to it yet ({availabilityLabel}), so nothing typed here would be
                    stored or sent anywhere.
                  </p>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">OpenAI Configuration</h4>
                  <div className="space-y-4">
                    <div>
                      <label htmlFor={apiKeyId} className="block text-sm mb-2">API Key</label>
                      <input
                        id={apiKeyId}
                        type="password"
                        value=""
                        readOnly
                        disabled
                        aria-describedby={apiKeyHintId}
                        placeholder="sk-..."
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      />
                      <p id={apiKeyHintId} className="text-xs text-[var(--muted-foreground)] mt-2">
                        Set OPENAI_API_KEY in the backend environment instead.
                      </p>
                    </div>

                    <div>
                      <label htmlFor={modelSelectId} className="block text-sm mb-2">Model</label>
                      <select
                        id={modelSelectId}
                        disabled
                        defaultValue="gpt-4"
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      >
                        <option value="gpt-4">GPT-4</option>
                        <option value="gpt-4-turbo">GPT-4 Turbo</option>
                        <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">Local Model Configuration</h4>
                  <div className="space-y-4">
                    <div>
                      <label htmlFor={endpointId} className="block text-sm mb-2">Endpoint URL</label>
                      <input
                        id={endpointId}
                        type="text"
                        value=""
                        readOnly
                        disabled
                        aria-describedby={endpointHintId}
                        placeholder="http://localhost:11434"
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      />
                      <p id={endpointHintId} className="text-xs text-[var(--muted-foreground)] mt-2">
                        Set LOCAL_MODEL_PATH in the backend environment instead.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'data' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">Storage</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">
                        Documents, embeddings and conversations live on the server.
                      </p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        The backend does not report how much space they use, so
                        there are no figures to show here ({availabilityLabel}).
                      </p>
                    </div>

                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={clearCache}
                        disabled={isClearingCache}
                        className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
                      >
                        {isClearingCache && <Loader2 className="w-4 h-4 animate-spin" />}
                        <span>Clear Cache</span>
                      </button>
                      <button
                        type="button"
                        disabled
                        aria-label={`Export Data (${availabilityLabel})`}
                        className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        Export Data
                      </button>
                    </div>

                    {cacheResult && (
                      <p role="status" className="text-xs text-[var(--muted-foreground)]">
                        {cacheResult}
                      </p>
                    )}
                    {cacheError && (
                      <p role="alert" className="text-xs text-[var(--error)]">
                        {cacheError}
                      </p>
                    )}

                    <p className="text-xs text-[var(--muted-foreground)]">
                      Clear Cache drops the server&apos;s cached answers and
                      embeddings; sources and conversations are untouched.
                      Exporting everything at once is {availabilityLabel} — export
                      a conversation or a project from the toolbar instead.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">Notification Preferences</h4>
                  <div className="space-y-3">
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={notifyOnComplete}
                        onChange={(e) => setNotifyOnComplete(e.target.checked)}
                        className="w-4 h-4 mt-0.5 rounded border-[var(--border)]"
                      />
                      <div>
                        <p className="text-sm">Processing complete</p>
                        <p className="text-xs text-[var(--muted-foreground)]">
                          Show a message in this tab when a source finishes
                          processing, or fails.
                        </p>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'security' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">Privacy &amp; Security</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">
                        Your data stays in the deployment you run.
                      </p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        Sources, embeddings and conversations are stored by this
                        workspace&apos;s own backend. They are not encrypted at
                        rest, and they only reach an external model provider if
                        the server is configured to use one.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'about' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">About OpenNotebookLM</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">Version 0.1.0</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        An open-source implementation of Google NotebookLM
                      </p>
                    </div>
                    <div className="space-y-2">
                      <a
                        href={`${REPOSITORY_URL}#readme`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-sm text-[var(--primary)] hover:underline"
                      >
                        Documentation
                      </a>
                      <a
                        href={REPOSITORY_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-sm text-[var(--primary)] hover:underline"
                      >
                        GitHub Repository
                      </a>
                      <a
                        href={`${REPOSITORY_URL}/issues/new`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-sm text-[var(--primary)] hover:underline"
                      >
                        Report an Issue
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-3 p-6 border-t border-[var(--border)]">
            <button
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="px-4 py-2 text-sm bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base disabled:opacity-50 flex items-center gap-2"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  <span>Save Changes</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
