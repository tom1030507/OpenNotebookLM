'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import api from '@/lib/api';
import type {
  AnswerLength,
  ChatRole,
  ChatSettings,
  LLMModel,
  OutputLanguage,
} from '@/lib/api';
import useDialogFocus from '@/hooks/useDialogFocus';

// Matches CHAT_INSTRUCTIONS_MAX_LENGTH on the backend, which rejects longer text.
const INSTRUCTIONS_MAX_LENGTH = 2000;

const ROLES: { value: ChatRole; label: string; description: string }[] = [
  { value: 'default', label: 'Default', description: 'Direct answers grounded in your sources.' },
  { value: 'learning_guide', label: 'Learning guide', description: 'Explains step by step and checks understanding.' },
  { value: 'custom', label: 'Custom', description: 'Your own instructions for tone, focus and format.' },
];

const LENGTHS: { value: AnswerLength; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'longer', label: 'Longer' },
  { value: 'shorter', label: 'Shorter' },
];

const OUTPUT_LANGUAGES: { value: OutputLanguage; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'en', label: 'English' },
  { value: 'zh-Hant', label: '繁體中文' },
  { value: 'zh-Hans', label: '简体中文' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
];

interface ChatSettingsDialogProps {
  projectId: string;
  onClose: () => void;
  onOutputLanguageChanged?: () => void;
}

export default function ChatSettingsDialog({
  projectId,
  onClose,
  onOutputLanguageChanged,
}: ChatSettingsDialogProps) {
  const [settings, setSettings] = useState<ChatSettings | null>(null);
  const [models, setModels] = useState<LLMModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const initialOutputLanguage = useRef<OutputLanguage>('auto');
  const titleId = useId();
  const instructionsId = useId();
  const outputLanguageId = useId();
  const modelId = useId();

  useDialogFocus({
    isOpen: true,
    onClose,
    dismissible: !isSaving,
    dialogRef,
    initialFocusRef: closeRef,
  });

  useEffect(() => {
    let active = true;
    api.getChatSettings(projectId)
      .then((loaded) => {
        if (!active) return;
        initialOutputLanguage.current = loaded.output_language ?? 'auto';
        setSettings({
          ...loaded,
          output_language: initialOutputLanguage.current,
          model: loaded.model ?? null,
        });
      })
      .catch(() => { if (active) setError('Could not load chat settings.'); });
    api.getModels()
      .then((available) => { if (active) setModels(available); })
      .catch(() => { if (active) setModels([]); });
    return () => { active = false; };
  }, [projectId]);

  const update = (change: Partial<ChatSettings>) => {
    setSettings((current) => (current ? { ...current, ...change } : current));
  };

  const handleSave = async () => {
    if (!settings) return;
    setIsSaving(true);
    setError(null);
    try {
      await api.updateChatSettings(projectId, settings);
      if (settings.output_language !== initialOutputLanguage.current) {
        onOutputLanguageChanged?.();
      }
      onClose();
    } catch {
      setError('Could not save chat settings. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-[var(--overlay)] flex items-center justify-center z-50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--popover)] border border-[var(--border)] shadow-xl rounded-lg w-full max-w-md max-h-full overflow-y-auto"
      >
        <div className="p-6 border-b border-[var(--border)]">
          <div className="flex items-center justify-between">
            <h2 id={titleId} className="text-lg font-semibold">Chat settings</h2>
            <button
              ref={closeRef}
              onClick={onClose}
              type="button"
              aria-label="Close chat settings"
              title="Close chat settings"
              disabled={isSaving}
              className="p-1 hover:bg-[var(--muted)] rounded transition-base"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <p className="text-sm text-[var(--muted-foreground)] mt-2">
            Applies to every chat answer in this project. Answers stay grounded in your sources and cite them.
          </p>
        </div>

        <div className="p-6 space-y-6">
          {!settings ? (
            error ? (
              <p role="alert" className="text-sm text-[var(--error)]">{error}</p>
            ) : (
              <div className="flex justify-center">
                <Loader2 className="w-5 h-5 animate-spin" aria-label="Loading chat settings" />
              </div>
            )
          ) : (
            <>
              <fieldset className="space-y-3">
                <legend className="text-sm font-medium mb-3">Role</legend>
                {ROLES.map((role) => (
                  <label
                    key={role.value}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      settings.role === role.value
                        ? 'border-[var(--primary)] bg-[var(--primary)]/5'
                        : 'border-[var(--border)] hover:bg-[var(--muted)]'
                    }`}
                  >
                    <input
                      type="radio"
                      name="chat-role"
                      value={role.value}
                      checked={settings.role === role.value}
                      onChange={() => update({ role: role.value })}
                      className="mt-1"
                    />
                    <span>
                      <span className="block font-medium text-sm">{role.label}</span>
                      <span className="block text-xs text-[var(--muted-foreground)]">{role.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>

              {settings.role === 'custom' && (
                <div>
                  <label htmlFor={instructionsId} className="block text-sm font-medium mb-2">
                    Custom instructions
                  </label>
                  <textarea
                    id={instructionsId}
                    value={settings.instructions}
                    onChange={(e) => update({ instructions: e.target.value })}
                    maxLength={INSTRUCTIONS_MAX_LENGTH}
                    rows={4}
                    placeholder="For example: answer as a peer reviewer and point out weak evidence."
                    className="w-full px-3 py-2 bg-[var(--card)] border border-[var(--input)] rounded-lg resize-y focus:outline-none focus:ring-2 focus:ring-[var(--ring)] text-sm"
                  />
                  <p className="mt-1 text-xs text-[var(--muted-foreground)] text-right">
                    {settings.instructions.length}/{INSTRUCTIONS_MAX_LENGTH}
                  </p>
                </div>
              )}

              <div>
                <label htmlFor={outputLanguageId} className="block text-sm font-medium mb-2">
                  Output language
                </label>
                <select
                  id={outputLanguageId}
                  value={settings.output_language}
                  onChange={(event) => update({
                    output_language: event.target.value as OutputLanguage,
                  })}
                  className="w-full px-3 py-2 bg-[var(--card)] border border-[var(--input)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] text-sm"
                >
                  {OUTPUT_LANGUAGES.map((language) => (
                    <option key={language.value} value={language.value}>{language.label}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                  Auto keeps the current behavior, matching the question or source language.
                </p>
              </div>

              {(models.length > 0 || settings.model) && (
                <div>
                  <label htmlFor={modelId} className="block text-sm font-medium mb-2">
                    Default model
                  </label>
                  <select
                    id={modelId}
                    value={settings.model ?? ''}
                    onChange={(event) => update({ model: event.target.value || null })}
                    className="w-full px-3 py-2 bg-[var(--card)] border border-[var(--input)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] text-sm"
                  >
                    <option value="">Server default</option>
                    {settings.model && !models.some((model) => model.id === settings.model) && (
                      <option value={settings.model}>Unavailable: {settings.model}</option>
                    )}
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.provider} · {model.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <fieldset>
                <legend className="text-sm font-medium mb-3">Answer length</legend>
                <div className="flex gap-2">
                  {LENGTHS.map((length) => (
                    <label
                      key={length.value}
                      className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border cursor-pointer text-sm transition-colors ${
                        settings.answer_length === length.value
                          ? 'border-[var(--primary)] bg-[var(--primary)]/5'
                          : 'border-[var(--border)] hover:bg-[var(--muted)]'
                      }`}
                    >
                      <input
                        type="radio"
                        name="answer-length"
                        value={length.value}
                        checked={settings.answer_length === length.value}
                        onChange={() => update({ answer_length: length.value })}
                      />
                      {length.label}
                    </label>
                  ))}
                </div>
              </fieldset>

              {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
            </>
          )}
        </div>

        <div className="p-6 border-t border-[var(--border)] flex gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 px-4 py-2 border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!settings || isSaving}
            className="flex-1 px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg hover:opacity-90 transition-base disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isSaving && <Loader2 className="w-4 h-4 animate-spin" />}
            <span>{isSaving ? 'Saving...' : 'Save'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
