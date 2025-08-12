'use client';

import React, { useState } from 'react';
import { 
  X, 
  Settings as SettingsIcon,
  Moon,
  Sun,
  Globe,
  Key,
  Database,
  Bell,
  Shield,
  HelpCircle,
  ChevronRight,
  Save,
  Loader2
} from 'lucide-react';

interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = 'general' | 'api' | 'data' | 'notifications' | 'security' | 'about';

export default function Settings({ isOpen, onClose }: SettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('system');
  const [language, setLanguage] = useState('en');
  const [openaiKey, setOpenaiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [autoSave, setAutoSave] = useState(true);
  const [notifications, setNotifications] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    // Simulate save
    await new Promise(resolve => setTimeout(resolve, 1000));
    setIsSaving(false);
    onClose();
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
      <div className="bg-[var(--background)] rounded-lg w-full max-w-4xl max-h-[80vh] flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-64 border-r border-[var(--border)] bg-[var(--sidebar-bg)]">
          <div className="p-6 border-b border-[var(--border)]">
            <h2 className="text-lg font-semibold">Settings</h2>
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
              onClick={onClose}
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
                          return (
                            <button
                              key={option.value}
                              onClick={() => setTheme(option.value as typeof theme)}
                              className={`flex items-center gap-2 px-4 py-2 rounded-lg border transition-base ${
                                theme === option.value
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
                    </div>

                    <div>
                      <label className="block text-sm mb-2">Language</label>
                      <select
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      >
                        <option value="en">English</option>
                        <option value="zh">中文</option>
                        <option value="ja">日本語</option>
                        <option value="es">Español</option>
                        <option value="fr">Français</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">Behavior</h4>
                  <div className="space-y-3">
                    <label className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={autoSave}
                        onChange={(e) => setAutoSave(e.target.checked)}
                        className="w-4 h-4 rounded border-[var(--border)]"
                      />
                      <span className="text-sm">Auto-save conversations</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'api' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">OpenAI Configuration</h4>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm mb-2">API Key</label>
                      <div className="flex gap-2">
                        <input
                          type={showApiKey ? 'text' : 'password'}
                          value={openaiKey}
                          onChange={(e) => setOpenaiKey(e.target.value)}
                          placeholder="sk-..."
                          className="flex-1 px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                        />
                        <button
                          onClick={() => setShowApiKey(!showApiKey)}
                          className="px-4 py-2 border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base"
                        >
                          {showApiKey ? 'Hide' : 'Show'}
                        </button>
                      </div>
                      <p className="text-xs text-[var(--muted-foreground)] mt-2">
                        Your API key is stored securely and never shared.
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm mb-2">Model</label>
                      <select className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]">
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
                      <label className="block text-sm mb-2">Endpoint URL</label>
                      <input
                        type="text"
                        placeholder="http://localhost:11434"
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      />
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
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">Documents</span>
                        <span className="text-sm font-medium">124 MB</span>
                      </div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">Embeddings</span>
                        <span className="text-sm font-medium">56 MB</span>
                      </div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">Conversations</span>
                        <span className="text-sm font-medium">12 MB</span>
                      </div>
                      <div className="border-t border-[var(--border)] mt-3 pt-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">Total</span>
                          <span className="text-sm font-medium">192 MB</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      <button className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base">
                        Clear Cache
                      </button>
                      <button className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base">
                        Export Data
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">Notification Preferences</h4>
                  <div className="space-y-3">
                    <label className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={notifications}
                        onChange={(e) => setNotifications(e.target.checked)}
                        className="w-4 h-4 rounded border-[var(--border)]"
                      />
                      <div>
                        <p className="text-sm">Processing complete</p>
                        <p className="text-xs text-[var(--muted-foreground)]">
                          Notify when document processing is finished
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
                  <h4 className="text-sm font-medium mb-4">Privacy & Security</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">Your data is encrypted and stored locally.</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        We never share your documents or conversations with third parties.
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
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
                        Documentation
                      </a>
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
                        GitHub Repository
                      </a>
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
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
              className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base"
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
