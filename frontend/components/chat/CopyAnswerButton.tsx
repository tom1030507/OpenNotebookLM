'use client';

import React, { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import type { Message } from '@/lib/api';

/**
 * The answer as Markdown, with each `[Source N]` written as the `[N]` the
 * reader sees, so the copy matches the screen rather than the raw reply.
 */
export const answerAsMarkdown = (content: string): string => (
  content.replace(/\[Source\s+(\d+)\]/g, '[$1]').trim()
);

/** Copies an answer; selecting it by hand also picked up the Sources block (#241). */
export default function CopyAnswerButton({ message }: { message: Message }) {
  const [state, setState] = useState<'idle' | 'copied' | 'error'>('idle');

  useEffect(() => {
    if (state === 'idle') return;
    const timer = setTimeout(() => setState('idle'), 2000);
    return () => clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answerAsMarkdown(message.content));
      setState('copied');
    } catch {
      setState('error');
    }
  };

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded hover:bg-[var(--muted)] transition-base ${
        state === 'error' ? 'text-[var(--error)]' : 'text-[var(--muted-foreground)]'
      }`}
    >
      {state === 'copied' ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {state === 'copied' ? 'Copied' : state === 'error' ? 'Could not copy' : 'Copy'}
    </button>
  );
}
