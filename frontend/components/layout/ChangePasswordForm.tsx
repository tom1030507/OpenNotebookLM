'use client';

import React, { useId, useState } from 'react';
import api from '@/lib/api';

const inputClassName = 'w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm';

/**
 * Change the signed-in account's password (#248). Before this an account
 * created by an administrator, or whose password had been shared, had no way
 * to change it from the interface.
 */
export default function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const id = useId();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setOutcome({ ok: false, text: 'The new passwords do not match.' });
      return;
    }
    setSaving(true);
    setOutcome(null);
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmation('');
      setOutcome({ ok: true, text: 'Password changed.' });
    } catch (error) {
      setOutcome({
        ok: false,
        text: error instanceof Error ? error.message : 'The password could not be changed.',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      aria-labelledby={`${id}-title`}
      className="mt-5 space-y-3 border-t border-[var(--border)] pt-4"
    >
      <h3 id={`${id}-title`} className="text-sm font-medium">Change password</h3>
      <label className="block space-y-1 text-xs text-[var(--muted-foreground)]">
        <span>Current password</span>
        <input
          type="password"
          autoComplete="current-password"
          required
          maxLength={72}
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          className={inputClassName}
        />
      </label>
      <div className="space-y-1">
        <label className="block space-y-1 text-xs text-[var(--muted-foreground)]">
          <span>New password</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={72}
            aria-describedby={`${id}-rule`}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            className={inputClassName}
          />
        </label>
        <p id={`${id}-rule`} className="text-xs text-[var(--muted-foreground)]">8 to 72 characters.</p>
      </div>
      <label className="block space-y-1 text-xs text-[var(--muted-foreground)]">
        <span>Confirm new password</span>
        <input
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={72}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          className={inputClassName}
        />
      </label>
      {outcome && (
        <p
          role={outcome.ok ? 'status' : 'alert'}
          className={`text-xs ${outcome.ok ? 'text-[var(--muted-foreground)]' : 'text-[var(--error)]'}`}
        >
          {outcome.text}
        </p>
      )}
      <button
        type="submit"
        disabled={saving || !currentPassword || !newPassword || !confirmation}
        className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
      >
        {saving ? 'Changing…' : 'Change password'}
      </button>
    </form>
  );
}
