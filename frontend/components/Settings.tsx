'use client';

import React, { useState } from 'react';
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
import { uiCopy } from '@/lib/uiCopy';

interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = 'general' | 'api' | 'data' | 'notifications' | 'security' | 'about';

export default function Settings({ isOpen, onClose }: SettingsProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('system');
  const [language, setLanguage] = useState('zh-TW');
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
    { id: 'general', label: uiCopy.settings.general, icon: SettingsIcon },
    { id: 'api', label: uiCopy.settings.apiKeys, icon: Key },
    { id: 'data', label: uiCopy.settings.dataStorage, icon: Database },
    { id: 'notifications', label: uiCopy.settings.notifications, icon: Bell },
    { id: 'security', label: uiCopy.settings.security, icon: Shield },
    { id: 'about', label: uiCopy.settings.about, icon: HelpCircle },
  ];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-[var(--background)] rounded-lg w-full max-w-4xl max-h-[80vh] flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-64 border-r border-[var(--border)] bg-[var(--sidebar-bg)]">
          <div className="p-6 border-b border-[var(--border)]">
            <h2 className="text-lg font-semibold">{uiCopy.settings.title}</h2>
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
                  <h4 className="text-sm font-medium mb-4">外觀</h4>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm mb-2">主題</label>
                      <div className="flex gap-2">
                        {[
                          { value: 'light', icon: Sun, label: '淺色' },
                          { value: 'dark', icon: Moon, label: '深色' },
                          { value: 'system', icon: SettingsIcon, label: '跟隨系統' },
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
                      <label className="block text-sm mb-2">語言</label>
                      <select
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                      >
                        <option value="zh-TW">繁體中文</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">使用方式</h4>
                  <div className="space-y-3">
                    <label className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={autoSave}
                        onChange={(e) => setAutoSave(e.target.checked)}
                        className="w-4 h-4 rounded border-[var(--border)]"
                      />
                      <span className="text-sm">自動儲存對話</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'api' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">OpenAI 設定</h4>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm mb-2">API 金鑰</label>
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
                          {showApiKey ? '隱藏' : '顯示'}
                        </button>
                      </div>
                      <p className="text-xs text-[var(--muted-foreground)] mt-2">
                        你的 API 金鑰會安全儲存，絕不會分享給他人。
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm mb-2">模型</label>
                      <select className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)]">
                        <option value="gpt-4">GPT-4</option>
                        <option value="gpt-4-turbo">GPT-4 Turbo</option>
                        <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-medium mb-4">本機模型設定</h4>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm mb-2">端點 URL</label>
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
                  <h4 className="text-sm font-medium mb-4">儲存空間</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">文件</span>
                        <span className="text-sm font-medium">124 MB</span>
                      </div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">嵌入向量</span>
                        <span className="text-sm font-medium">56 MB</span>
                      </div>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm">對話</span>
                        <span className="text-sm font-medium">12 MB</span>
                      </div>
                      <div className="border-t border-[var(--border)] mt-3 pt-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">合計</span>
                          <span className="text-sm font-medium">192 MB</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      <button className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base">
                        清除快取
                      </button>
                      <button className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base">
                        匯出資料
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">通知偏好設定</h4>
                  <div className="space-y-3">
                    <label className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={notifications}
                        onChange={(e) => setNotifications(e.target.checked)}
                        className="w-4 h-4 rounded border-[var(--border)]"
                      />
                      <div>
                        <p className="text-sm">處理完成</p>
                        <p className="text-xs text-[var(--muted-foreground)]">
                          文件處理完成時通知我
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
                  <h4 className="text-sm font-medium mb-4">隱私與安全性</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">你的資料會加密後儲存在本機。</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        我們不會將你的文件或對話分享給第三方。
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'about' && (
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-medium mb-4">關於 OpenNotebookLM</h4>
                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)]">
                      <p className="text-sm mb-2">版本 0.1.0</p>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        Google NotebookLM 的開源實作
                      </p>
                    </div>
                    <div className="space-y-2">
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
                        使用文件
                      </a>
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
                        GitHub 儲存庫
                      </a>
                      <a href="#" className="block text-sm text-[var(--primary)] hover:underline">
                        回報問題
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
              {uiCopy.actions.cancel}
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="px-4 py-2 text-sm bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base disabled:opacity-50 flex items-center gap-2"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>儲存中...</span>
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  <span>儲存變更</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
