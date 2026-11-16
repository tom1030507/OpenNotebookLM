'use client';

import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import useDialogFocus from '@/hooks/useDialogFocus';
import { settleDialog, useDialogRequests, type DialogRequest } from '@/lib/dialogs';

/** Renders the confirmation or text question asked through lib/dialogs. */
export default function DialogHost() {
  const active = useDialogRequests((state) => state.active);
  if (!active) return null;
  // Keyed on the request, so a replaced question starts with fresh state.
  return <ActiveDialog key={active.id} request={active} />;
}

function ActiveDialog({ request }: { request: DialogRequest }) {
  const dialogRef = useRef<HTMLFormElement>(null);
  const firstFieldRef = useRef<HTMLInputElement & HTMLButtonElement>(null);
  const titleId = useId();
  const inputId = useId();
  const [text, setText] = useState(request.kind === 'text' ? request.initialValue : '');
  const cancel = () => settleDialog(request.kind === 'confirm' ? false : null);

  useDialogFocus({
    isOpen: true,
    onClose: cancel,
    dialogRef,
    initialFocusRef: firstFieldRef,
  });

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[var(--overlay)] p-4">
      <form
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={(event) => {
          event.preventDefault();
          settleDialog(request.kind === 'confirm' ? true : text);
        }}
        className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--popover)] p-5 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold">{request.title}</h2>
        {request.kind === 'confirm' && request.message && (
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">{request.message}</p>
        )}
        {request.kind === 'text' && (
          <div className="mt-3">
            <label htmlFor={inputId} className="mb-1 block text-sm text-[var(--muted-foreground)]">
              {request.label}
            </label>
            <input
              id={inputId}
              ref={firstFieldRef}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onFocus={(event) => event.target.select()}
              className="h-9 w-full rounded-md border border-[var(--input)] bg-[var(--card)] px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            ref={request.kind === 'confirm' ? firstFieldRef : undefined}
            className="h-9 rounded-md border border-[var(--input)] px-3 text-sm hover:bg-[var(--muted)]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={request.kind === 'text' && !text.trim()}
            className={`h-9 rounded-md px-3 text-sm font-medium disabled:opacity-50 ${
              request.kind === 'confirm' && request.danger
                ? 'bg-[var(--error)] text-white hover:opacity-90'
                : 'bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary-hover)]'
            }`}
          >
            {request.confirmLabel}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
