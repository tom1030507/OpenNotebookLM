'use client';

import React, { useId, useRef } from 'react';
import { X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';

interface TopNavInfoDialogProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * Small modal used by the top navigation's informational panels (profile, help,
 * notifications). It reuses the shared focus lifecycle so these dialogs behave
 * exactly like the project, settings and export dialogs.
 */
export default function TopNavInfoDialog({ title, onClose, children }: TopNavInfoDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useDialogFocus({
    isOpen: true,
    onClose,
    dialogRef,
    initialFocusRef: closeRef,
  });

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--background)] rounded-lg w-full max-w-md max-h-[80vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
          <button
            ref={closeRef}
            onClick={onClose}
            type="button"
            aria-label={`Close ${title.toLowerCase()} dialog`}
            title={`Close ${title.toLowerCase()} dialog`}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
