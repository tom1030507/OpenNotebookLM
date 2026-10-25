'use client';

import React, { useEffect, useState } from 'react';
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import api from '@/lib/api';
import type { MindMap, Note, VideoSummary } from '@/lib/api';
import useNotes from '@/store/useNotes';
import useStore from '@/store/useStore';
import MarkdownRenderer from '../MarkdownRenderer';

const MindMapDialog = React.lazy(() => import('../MindMapDialog'));
const VideoSummaryDialog = React.lazy(() => import('../VideoSummaryDialog'));

interface Draft {
  /** `null` while writing a new note. */
  noteId: string | null;
  title: string;
  content: string;
}

const inputClass = 'w-full px-3 py-2 bg-[var(--card)] border border-[var(--input)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]';
const actionClass = 'inline-flex items-center gap-1 px-2 py-1 text-xs rounded hover:bg-[var(--muted)] transition-base disabled:opacity-50';
const EMPTY_NOTES: Note[] = [];

export default function NotesSection({ projectId }: { projectId: string | null }) {
  const canEdit = useStore((state) => state.currentProject?.id === projectId
    && (state.currentProject.role === 'owner' || state.currentProject.role === 'editor'));
  const notes = useNotes((state) => state.projectId === projectId ? state.notes : EMPTY_NOTES);
  const loading = useNotes((state) => (
    state.projectId === projectId ? state.loading : projectId !== null
  ));
  const loadError = useNotes((state) => state.projectId === projectId ? state.error : '');
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void useNotes.getState().load(projectId);
    setOpenId(null);
    setDraft(null);
    setError('');
  }, [projectId]);

  useEffect(() => {
    if (!canEdit) setDraft(null);
  }, [canEdit]);

  if (!projectId) return null;

  const viewerNote = notes.find((note) => note.id === openId && note.origin === 'studio');

  const saveDraft = async () => {
    if (!canEdit || !draft || !draft.title.trim()) return;
    setSaving(true);
    setError('');
    try {
      const fields = { title: draft.title.trim(), content: draft.content };
      const note = draft.noteId
        ? await api.updateNote(projectId, draft.noteId, fields)
        : await api.createNote(projectId, fields);
      useNotes.getState().upsert(note);
      setDraft(null);
      setOpenId(note.id);
    } catch {
      setError('The note could not be saved. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const deleteNote = async (note: Note) => {
    if (!canEdit) return;
    if (!confirm(`Delete the note "${note.title}"?`)) return;
    setError('');
    try {
      await api.deleteNote(projectId, note.id);
      useNotes.getState().remove(projectId, note.id);
    } catch {
      setError('The note could not be deleted. Please try again.');
    }
  };

  const editor = canEdit && draft && (
    <div className="space-y-2 p-3 bg-[var(--card)] border border-[var(--border)] rounded-lg">
      <input
        aria-label="Note title"
        placeholder="Title"
        value={draft.title}
        onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        maxLength={200}
        className={inputClass}
      />
      <textarea
        aria-label="Note content"
        placeholder="Write in Markdown…"
        value={draft.content}
        onChange={(e) => setDraft({ ...draft, content: e.target.value })}
        rows={8}
        className={`${inputClass} resize-y`}
      />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setDraft(null)} className={actionClass}>
          Cancel
        </button>
        <button
          type="button"
          onClick={saveDraft}
          disabled={saving || !draft.title.trim()}
          className={`${actionClass} bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary-hover)]`}
        >
          {saving && <Loader2 className="w-3 h-3 animate-spin" />}
          Save note
        </button>
      </div>
    </div>
  );

  return (
    <>
    <section aria-label="Notes" className="mt-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">Notes</h3>
        {canEdit && (
          <button
            type="button"
            onClick={() => setDraft({ noteId: null, title: '', content: '' })}
            disabled={draft?.noteId === null}
            className={actionClass}
          >
            <Plus className="w-3.5 h-3.5" />
            New note
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="mb-2 text-xs text-[var(--error)]">{error}</p>
      )}
      {/* Not an alert: the list loads on its own, and announcing that over the
          Studio action the reader just started would interrupt it. */}
      {loadError && (
        <p className="mb-2 text-xs text-[var(--error)]">{loadError}</p>
      )}

      {draft?.noteId === null && editor}

      {loading ? (
        <p className="text-xs text-[var(--muted-foreground)]">Loading notes…</p>
      ) : notes.length === 0 && !draft ? (
        <p className="text-xs text-[var(--muted-foreground)]">
          No notes yet. Save an answer from the chat or write your own.
        </p>
      ) : (
        <ul className="space-y-2 mt-2">
          {notes.map((note) => (
            <li key={note.id}>
              {draft?.noteId === note.id ? editor : (
                <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg">
                  <div className="flex items-start">
                    <button
                      type="button"
                      aria-expanded={openId === note.id}
                      onClick={() => setOpenId(openId === note.id ? null : note.id)}
                      className="min-w-0 flex-1 p-3 text-left text-sm font-medium break-words"
                    >
                      {note.title}
                      {note.origin === 'answer' && (
                        <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
                          Saved answer
                        </span>
                      )}
                      {note.origin === 'studio' && (
                        <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
                          Studio · {note.studio_kind === 'mindmap' ? 'Mind map'
                            : note.studio_kind === 'video_summary' ? 'Video summary' : 'Report'}
                        </span>
                      )}
                    </button>
                    {canEdit && note.origin === 'studio' && note.studio_kind !== 'report' && (
                      <button
                        type="button"
                        onClick={() => deleteNote(note)}
                        aria-label={`Delete note ${note.title}`}
                        className="shrink-0 self-stretch px-3 text-[var(--error)] hover:bg-[var(--muted)]"
                      >
                        <Trash2 aria-hidden="true" className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  {openId === note.id
                    && (note.origin !== 'studio' || note.studio_kind === 'report') && (
                    <div className="px-3 pb-3">
                      <MarkdownRenderer content={note.content} className="text-sm" />
                      {canEdit && (
                        <div className="flex justify-end gap-2 mt-2">
                          <button
                            type="button"
                            onClick={() => setDraft({
                              noteId: note.id, title: note.title, content: note.content,
                            })}
                            className={actionClass}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteNote(note)}
                            className={`${actionClass} text-[var(--error)]`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
      {viewerNote?.studio_kind === 'mindmap' && viewerNote.payload_json && (
        <React.Suspense fallback={<div role="status">Loading saved mind map…</div>}>
          <MindMapDialog
            map={viewerNote.payload_json as MindMap}
            onClose={() => setOpenId(null)}
          />
        </React.Suspense>
      )}
      {viewerNote?.studio_kind === 'video_summary' && viewerNote.payload_json && (
        <React.Suspense fallback={<div role="status">Loading saved video summary…</div>}>
          <VideoSummaryDialog
            summary={viewerNote.payload_json as VideoSummary}
            onClose={() => setOpenId(null)}
          />
        </React.Suspense>
      )}
    </>
  );
}
