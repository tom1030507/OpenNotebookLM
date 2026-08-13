'use client';

import React, { useState } from 'react';
import { AlertCircle, FolderPlus, Loader2, X } from 'lucide-react';
import useStore from '@/store/useStore';

interface ProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ProjectDialog({ isOpen, onClose }: ProjectDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const { createProject, selectProject } = useStore();

  const handleClose = () => {
    setName('');
    setDescription('');
    setError('');
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!name.trim()) {
      setError('\u8ACB\u8F38\u5165\u5C08\u6848\u540D\u7A31');
      return;
    }

    setIsCreating(true);
    setError('');

    try {
      const project = await createProject(name.trim(), description.trim() || undefined);
      selectProject(project);
      setName('');
      setDescription('');
      handleClose();
    } catch (caughtError: unknown) {
      setError(caughtError instanceof Error ? caughtError.message : '\u5EFA\u7ACB\u5C08\u6848\u5931\u6557');
    } finally {
      setIsCreating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-dialog-title"
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
    >
      <div className="bg-[var(--background)] rounded-lg w-full max-w-md">
        <div className="flex items-center justify-between p-6 border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[var(--primary)] bg-opacity-10 flex items-center justify-center">
              <FolderPlus className="w-5 h-5 text-[var(--primary)]" />
            </div>
            <h2 id="project-dialog-title" className="text-lg font-semibold">
              {'\u5EFA\u7ACB\u65B0\u5C08\u6848'}
            </h2>
          </div>
          <button
            onClick={handleClose}
            aria-label={'\u95DC\u9589\u5EFA\u7ACB\u5C08\u6848\u5C0D\u8A71\u6846'}
            disabled={isCreating}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              {'\u5C08\u6848\u540D\u7A31'} <span className="text-red-500">*</span>
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={'\u4F8B\u5982\uFF1A\u7814\u7A76\u8AD6\u6587\u3001\u6703\u8B70\u7B46\u8A18'}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
              disabled={isCreating}
              autoFocus
            />
          </div>

          <div>
            <label htmlFor="description" className="block text-sm font-medium mb-2">
              {'\u5C08\u6848\u8AAA\u660E'}
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={'\u9078\u586B\u7684\u5C08\u6848\u8AAA\u660E'}
              rows={3}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base resize-none"
              disabled={isCreating}
            />
          </div>

          <div className="text-xs text-[var(--muted-foreground)]">
            <p>{'\u5C08\u6848\u53EF\u5354\u52A9\u60A8\u6574\u7406\u6587\u4EF6\u8207\u5C0D\u8A71\u3002'}</p>
            <p className="mt-1">{'\u60A8\u53EF\u5728\u5C08\u6848\u4E2D\u52A0\u5165 PDF\u3001\u7DB2\u5740\u3001YouTube \u5F71\u7247\u7B49\u4F86\u6E90\u3002'}</p>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={isCreating}
              className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
            >
              {'\u53D6\u6D88'}
            </button>
            <button
              type="submit"
              disabled={isCreating || !name.trim()}
              className="px-4 py-2 text-sm bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isCreating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>{'\u5EFA\u7ACB\u4E2D...'}</span>
                </>
              ) : (
                <span>{'\u5EFA\u7ACB\u5C08\u6848'}</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
