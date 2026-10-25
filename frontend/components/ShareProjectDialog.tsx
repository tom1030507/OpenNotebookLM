'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { Loader2, Trash2, X } from 'lucide-react';
import api, { type Project, type ProjectMember } from '@/lib/api';
import useDialogFocus from '@/hooks/useDialogFocus';

interface ShareProjectDialogProps {
  project: Project;
  isOpen: boolean;
  onClose: () => void;
}

export default function ShareProjectDialog({
  project,
  isOpen,
  onClose,
}: ShareProjectDialogProps) {
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [identity, setIdentity] = useState('');
  const [identityType, setIdentityType] = useState<'username' | 'email'>('username');
  const [role, setRole] = useState<'viewer' | 'editor'>('viewer');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);
  const identityRef = useRef<HTMLInputElement>(null);
  const titleId = useId();

  useDialogFocus({
    isOpen,
    onClose,
    dismissible: !saving,
    dialogRef,
    initialFocusRef: identityRef,
  });

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    setLoading(true);
    setError('');
    api.getProjectMembers(project.id)
      .then((result) => { if (active) setMembers(result); })
      .catch(() => { if (active) setError('Could not load project members.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOpen, project.id]);

  if (!isOpen) return null;

  const fail = (caught: unknown) => {
    setError(caught instanceof Error ? caught.message : 'Could not update project members.');
  };

  const addMember = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = identity.trim();
    if (!value || saving) return;
    setSaving(true);
    setError('');
    try {
      const member = await api.addProjectMember(project.id, {
        [identityType]: value,
        role,
      });
      setMembers((current) => [...current, member]);
      setIdentity('');
    } catch (caught) {
      fail(caught);
    } finally {
      setSaving(false);
    }
  };

  const changeRole = async (member: ProjectMember, nextRole: 'viewer' | 'editor') => {
    if (saving || nextRole === member.role) return;
    setSaving(true);
    setError('');
    try {
      const updated = await api.updateProjectMember(project.id, member.user_id, {
        role: nextRole,
      });
      setMembers((current) => current.map((item) => (
        item.user_id === updated.user_id ? updated : item
      )));
    } catch (caught) {
      fail(caught);
    } finally {
      setSaving(false);
    }
  };

  const removeMember = async (member: ProjectMember) => {
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      await api.removeProjectMember(project.id, member.user_id);
      setMembers((current) => current.filter((item) => item.user_id !== member.user_id));
    } catch (caught) {
      fail(caught);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-lg rounded-lg bg-[var(--background)]"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] p-5">
          <h2 id={titleId} className="text-lg font-semibold">Share {project.name}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close share project dialog"
            disabled={saving}
            className="rounded-lg p-2 hover:bg-[var(--muted)]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 p-5">
          <form onSubmit={addMember} className="space-y-3">
            <label className="block text-sm font-medium" htmlFor="share-member-identity">
              Username or email
            </label>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
              <input
                ref={identityRef}
                id="share-member-identity"
                value={identity}
                onChange={(event) => setIdentity(event.target.value)}
                autoComplete="off"
                required
                className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
              />
              <select
                aria-label="Account identifier type"
                value={identityType}
                onChange={(event) => setIdentityType(event.target.value as 'username' | 'email')}
                className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-sm"
              >
                <option value="username">Username</option>
                <option value="email">Email</option>
              </select>
              <select
                aria-label="Role for new member"
                value={role}
                onChange={(event) => setRole(event.target.value as 'viewer' | 'editor')}
                className="justify-self-start rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-sm"
              >
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
              </select>
              <button
                type="submit"
                disabled={saving || !identity.trim()}
                className="justify-self-end rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
              >
                Add member
              </button>
            </div>
          </form>

          {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
          {loading ? (
            <p role="status" className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading members…
            </p>
          ) : (
            <ul aria-label="Project members" className="divide-y divide-[var(--border)]">
              {members.map((member) => (
                <li key={member.user_id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{member.username}</p>
                    <p className="truncate text-xs text-[var(--muted-foreground)]">{member.email}</p>
                  </div>
                  {member.role === 'owner' ? (
                    <span className="text-sm text-[var(--muted-foreground)]">Owner</span>
                  ) : (
                    <>
                      <select
                        aria-label={`Role for ${member.username}`}
                        value={member.role}
                        disabled={saving}
                        onChange={(event) => changeRole(
                          member, event.target.value as 'viewer' | 'editor',
                        )}
                        className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-sm"
                      >
                        <option value="viewer">Viewer</option>
                        <option value="editor">Editor</option>
                      </select>
                      <button
                        type="button"
                        aria-label={`Remove ${member.username}`}
                        title={`Remove ${member.username}`}
                        disabled={saving}
                        onClick={() => void removeMember(member)}
                        className="rounded p-2 text-[var(--error)] hover:bg-[var(--muted)] disabled:opacity-50"
                      >
                        <Trash2 aria-hidden="true" className="h-4 w-4" />
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
