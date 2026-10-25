'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import api from '@/lib/api';
import type { AnswerLength, ChatRole, ChatSettings } from '@/lib/api';
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

interface ChatSettingsDialogProps {
  projectId: string;
  onClose: () => void;
}

export default function ChatSettingsDialog({ projectId, onClose }: ChatSettingsDialogProps) {
  const [settings, setSettings] = useState<ChatSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const instructionsId = useId();

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
      .then((loaded) => { if (active) setSettings(loaded); })
      .catch(() => { if (active) setError('Could not load chat settings.'); });
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
      onClose();
    } catch {
      setError('Could not save chat settings. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--card)] border border-[var(--border)] shadow-xl rounded-lg w-full max-w-md max-h-full overflow-y-auto"
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
            Applies to every answer in this project. Answers always stay grounded in your sources and cite them.
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
