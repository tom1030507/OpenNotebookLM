'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Citation } from '@/lib/api';

export default function InlineCitation({ id, citation }: { id: number; citation: Citation }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hovered = useRef(false);
  const previewId = useId();

  const clearCloseTimer = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    closeTimer.current = null;
  };
  const show = () => {
    clearCloseTimer();
    setOpen(true);
  };
  const enter = () => {
    hovered.current = true;
    show();
  };
  const leave = () => {
    hovered.current = false;
    clearCloseTimer();
    // Allow the pointer to cross the gap to the portalled preview so readers
    // can inspect and select its text without the card disappearing.
    closeTimer.current = setTimeout(() => {
      if (document.activeElement !== triggerRef.current) setOpen(false);
    }, 150);
  };

  useEffect(() => clearCloseTimer, []);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current || !previewRef.current) return;
    const trigger = triggerRef.current.getBoundingClientRect();
    const preview = previewRef.current.getBoundingClientRect();
    const below = trigger.bottom + 8;
    const top = below + preview.height <= window.innerHeight - 12
      ? below
      : Math.max(12, trigger.top - preview.height - 8);
    const left = Math.max(12, Math.min(trigger.left, window.innerWidth - preview.width - 12));
    setPosition({ top, left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const dismiss = () => setOpen(false);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      if (!triggerRef.current?.contains(event.target) && !previewRef.current?.contains(event.target)) dismiss();
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && previewRef.current?.contains(event.target)) return;
      dismiss();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open]);

  return (
    <span className="not-prose">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Preview source ${id}`}
        aria-describedby={open ? previewId : undefined}
        aria-expanded={open}
        onMouseEnter={enter}
        onMouseLeave={leave}
        onFocus={show}
        onBlur={() => { if (!hovered.current) setOpen(false); }}
        onClick={show}
        className="inline rounded px-0.5 font-medium text-[var(--primary)] hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
      >
        [{id}]
      </button>
      {open && createPortal(
        <div
          ref={previewRef}
          id={previewId}
          role="tooltip"
          onMouseEnter={enter}
          onMouseLeave={leave}
          className="fixed z-[100] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 text-sm text-[var(--card-foreground)] shadow-lg break-words"
          style={{ ...position, width: 'min(360px, calc(100vw - 24px))', maxHeight: 'min(320px, calc(100vh - 24px))' }}
        >
          <p className="font-semibold">[{id}] {citation.source}</p>
          {citation.page != null && <p className="mt-1 text-xs text-[var(--muted-foreground)]">Page {citation.page}</p>}
          <p className="mt-2 leading-relaxed">{citation.text?.replace(/\s+/g, ' ').trim() || 'No excerpt available.'}</p>
        </div>,
        document.body,
      )}
    </span>
  );
}
