import { create } from 'zustand';
import api from '@/lib/api';
import type { Note } from '@/lib/api';

interface NotesState {
  /** The project `notes` belong to; anything for another project is dropped. */
  projectId: string | null;
  notes: Note[];
  loading: boolean;
  error: string;
  load: (projectId: string | null) => Promise<void>;
  /** Insert or replace a note the server just returned. */
  upsert: (note: Note) => void;
  remove: (projectId: string, noteId: string) => void;
}

// Separate from useStore so the chat (which saves answers) and the Studio list
// share one copy without either reaching into the other's component state.
const useNotes = create<NotesState>()((set, get) => ({
  projectId: null,
  notes: [],
  loading: false,
  error: '',

  load: async (projectId) => {
    set({ projectId, notes: [], error: '', loading: projectId !== null });
    if (projectId === null) return;
    try {
      const notes = await api.listNotes(projectId);
      if (get().projectId === projectId) set({ notes, loading: false });
    } catch {
      if (get().projectId === projectId) {
        set({ loading: false, error: 'Notes could not be loaded.' });
      }
    }
  },

  upsert: (note) => {
    if (get().projectId !== note.project_id) return;
    const others = get().notes.filter((existing) => existing.id !== note.id);
    const isNew = others.length === get().notes.length;
    // A new note goes first, matching the server's newest-first order; an edit
    // keeps its place.
    set({
      notes: isNew
        ? [note, ...others]
        : get().notes.map((existing) => (existing.id === note.id ? note : existing)),
    });
  },

  remove: (projectId, noteId) => {
    if (get().projectId !== projectId) return;
    set({ notes: get().notes.filter((note) => note.id !== noteId) });
  },
}));

export default useNotes;
