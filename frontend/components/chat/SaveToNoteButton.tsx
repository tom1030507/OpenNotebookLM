'use client';

import React, { useState } from 'react';
import { BookmarkPlus, Check, Loader2 } from 'lucide-react';
import api from '@/lib/api';
import type { Message } from '@/lib/api';
import useStore from '@/store/useStore';
import useNotes from '@/store/useNotes';

const TITLE_LENGTH = 80;

/** Name the note after the question the answer replied to. */
function noteTitle(answer: Message): string {
  const messages = useStore.getState().messages;
  const index = messages.findIndex((message) => message.id === answer.id);
  const question = messages.slice(0, Math.max(index, 0)).reverse()
    .find((message) => message.role === 'user');
  const text = (question?.content || 'Saved answer').replace(/\s+/g, ' ').trim();
  return text.length > TITLE_LENGTH ? `${text.slice(0, TITLE_LENGTH - 1)}…` : text;
}

export default function SaveToNoteButton({ message }: { message: Message }) {
  const project = useStore((state) => state.currentProject);
  const projectId = project?.id ?? null;
  const canEdit = project?.role === 'owner' || project?.role === 'editor';
  const alreadySaved = useNotes((state) => (
    state.projectId === projectId
    && state.notes.some((note) => note.source_message_id === message.id)
  ));
  const notesLoaded = useNotes((state) => (
    state.projectId === projectId && !state.loading && !state.error
  ));
  const [savedFor, setSavedFor] = useState<{ projectId: string; messageId: string } | null>(null);
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle');

  const save = async () => {
    if (!projectId || !canEdit) return;
    setState('saving');
    try {
      // The server writes the content from the stored answer, so the note keeps
      // exactly the citations the answer was given.
      const note = await api.createNote(projectId, {
        title: noteTitle(message),
        source_message_id: message.id,
      });
      useNotes.getState().upsert(note);
      setSavedFor({ projectId, messageId: message.id });
      setState('idle');
    } catch {
      setState('error');
    }
  };

  const isSaved = alreadySaved || (!notesLoaded
    && savedFor?.projectId === projectId && savedFor.messageId === message.id);
  const visibleState = isSaved ? 'saved' : state;
  const label = {
    idle: 'Save to note',
    saving: 'Saving…',
    saved: 'Saved to notes',
    error: 'Could not save. Try again',
  }[visibleState];

  if (!canEdit) return null;

  return (
    <button
      type="button"
      onClick={save}
      disabled={visibleState === 'saving' || visibleState === 'saved'}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded hover:bg-[var(--muted)] transition-base disabled:cursor-default ${
        visibleState === 'error' ? 'text-[var(--error)]' : 'text-[var(--muted-foreground)]'
      }`}
    >
      {visibleState === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
        : visibleState === 'saved' ? <Check className="w-3.5 h-3.5" />
          : <BookmarkPlus className="w-3.5 h-3.5" />}
      {label}
    </button>
  );
}
