'use client';

import React, { useId, useRef, useState } from 'react';
import { AlertCircle, FolderPlus, Loader2, X } from 'lucide-react';
import useStore from '@/store/useStore';
import useDialogFocus from '@/hooks/useDialogFocus';

interface ProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ProjectDialog({ isOpen, onClose }: ProjectDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const nameInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { createProject, selectProject } = useStore();

  const handleClose = () => {
    setName('');
    setDescription('');
    setError('');
    onClose();
  };

  useDialogFocus({
    isOpen,
    onClose: handleClose,
    dismissible: !isCreating,
    dialogRef,
    initialFocusRef: nameInputRef,
  });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    setIsCreating(true);
    setError('');

    try {
      const project = await createProject(
        // Left blank, the project is titled from its sources once they are read.
        name.trim() || undefined,
        description.trim() || undefined,
      );
      if (!project) return;
      selectProject(project);
      setName('');
      setDescription('');
      handleClose();
    } catch (caughtError: unknown) {
      setError(caughtError instanceof Error ? caughtError.message : 'Failed to create project');
    } finally {
      setIsCreating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--card)] border border-[var(--border)] shadow-xl rounded-lg w-full max-w-md"
      >
        <div className="flex items-center justify-between p-6 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <FolderPlus className="w-4 h-4 text-[var(--muted-foreground)]" aria-hidden="true" />
            <h2 id={titleId} className="text-base font-semibold">
              {'Create New Project'}
            </h2>
          </div>
          <button
            onClick={handleClose}
            type="button"
            aria-label={'Close create project dialog'}
            title={'Close create project dialog'}
            disabled={isCreating}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-4 bg-[var(--error-bg)] border border-[var(--error)] rounded-lg flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-[var(--error)]" />
              <p className="text-sm text-[var(--error)]">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              {'Project Name'}
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={'Leave blank to name it from your sources'}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
              ref={nameInputRef}
              disabled={isCreating}
            />
          </div>

          <div>
            <label htmlFor="description" className="block text-sm font-medium mb-2">
              {'Project Description'}
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={'Optional project description'}
              rows={3}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base resize-none"
              disabled={isCreating}
            />
          </div>

          <div className="text-xs text-[var(--muted-foreground)]">
            <p>{'Projects help you organise your documents and conversations.'}</p>
            <p className="mt-1">{'You can add files, URLs, YouTube videos and more to a project.'}</p>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={isCreating}
              className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
            >
              {'Cancel'}
            </button>
            <button
              type="submit"
              disabled={isCreating}
              className="px-4 py-2 text-sm bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg hover:opacity-90 transition-base disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isCreating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>{'Creating...'}</span>
                </>
              ) : (
                <span>{'Create Project'}</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
