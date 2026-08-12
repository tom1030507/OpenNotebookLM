'use client';

import React, { useState } from 'react';
import { 
  X, 
  FolderPlus, 
  Loader2, 
  AlertCircle,
  CheckCircle
} from 'lucide-react';
import useStore from '@/store/useStore';
import { uiCopy } from '@/lib/uiCopy';

interface ProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export default function ProjectDialog({ isOpen, onClose, onSuccess }: ProjectDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  
  const { createProject, selectProject } = useStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!name.trim()) {
      setError(uiCopy.projectDialog.nameRequired);
      return;
    }
    
    setIsCreating(true);
    setError('');
    
    try {
      const project = await createProject(name.trim(), description.trim() || undefined);
      selectProject(project);
      setSuccess(true);
      
      setTimeout(() => {
        onSuccess?.();
        onClose();
        // Reset form
        setName('');
        setDescription('');
        setSuccess(false);
      }, 1500);
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : uiCopy.projectDialog.createFailed);
    } finally {
      setIsCreating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-[var(--background)] rounded-lg w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[var(--primary)] bg-opacity-10 flex items-center justify-center">
              <FolderPlus className="w-5 h-5 text-[var(--primary)]" />
            </div>
            <h2 className="text-lg font-semibold">{uiCopy.projectDialog.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Success Message */}
          {success && (
            <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-center gap-3">
              <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
              <p className="text-sm text-green-800 dark:text-green-200">
                {uiCopy.projectDialog.success}
              </p>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              {uiCopy.projectDialog.name} <span className="text-red-500">*</span>
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={uiCopy.projectDialog.namePlaceholder}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
              disabled={isCreating || success}
              autoFocus
            />
          </div>

          <div>
            <label htmlFor="description" className="block text-sm font-medium mb-2">
              {uiCopy.projectDialog.description}
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={uiCopy.projectDialog.descriptionPlaceholder}
              rows={3}
              className="w-full px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base resize-none"
              disabled={isCreating || success}
            />
          </div>

          <div className="text-xs text-[var(--muted-foreground)]">
            <p>{uiCopy.projectDialog.help}</p>
            <p className="mt-1">{uiCopy.projectDialog.sourceHelp}</p>
          </div>
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-6 border-t border-[var(--border)]">
          <button
            type="button"
            onClick={onClose}
            disabled={isCreating || success}
            className="px-4 py-2 text-sm border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
          >
            {uiCopy.actions.cancel}
          </button>
          <button
            onClick={handleSubmit}
            disabled={isCreating || success || !name.trim()}
            className="px-4 py-2 text-sm bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isCreating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{uiCopy.projectDialog.creating}</span>
              </>
            ) : success ? (
              <>
                <CheckCircle className="w-4 h-4" />
                <span>{uiCopy.projectDialog.created}</span>
              </>
            ) : (
              <span>{uiCopy.projectDialog.create}</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
