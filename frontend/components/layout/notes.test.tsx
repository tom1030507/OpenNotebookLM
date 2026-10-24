// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NotesSection from './NotesSection';
import SaveToNoteButton from '../chat/SaveToNoteButton';
import useStore from '@/store/useStore';
import useNotes from '@/store/useNotes';
import api from '@/lib/api';
import type { Message, Note, Project } from '@/lib/api';

const note = (fields: Partial<Note>): Note => ({
  id: 'note-1',
  project_id: 'project-1',
  title: 'First',
  content: 'Body',
  origin: 'manual',
  source_message_id: null,
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  ...fields,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
  useNotes.setState({ projectId: null, notes: [], loading: false, error: '' });
});

describe('Studio notes', () => {
  it('lists, creates and deletes notes', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({})]);
    const create = vi.spyOn(api, 'createNote').mockResolvedValue(
      note({ id: 'note-2', title: 'Second', content: '# Hi' }));
    const remove = vi.spyOn(api, 'deleteNote').mockResolvedValue();
    vi.stubGlobal('confirm', () => true);

    render(<NotesSection projectId="project-1" />);
    expect(await screen.findByText('First')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'New note' }));
    fireEvent.change(screen.getByLabelText('Note title'), { target: { value: 'Second' } });
    fireEvent.change(screen.getByLabelText('Note content'), { target: { value: '# Hi' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

    await waitFor(() => expect(create).toHaveBeenCalledWith(
      'project-1', { title: 'Second', content: '# Hi' }));
    expect(useNotes.getState().notes.map((n) => n.title)).toEqual(['Second', 'First']);

    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith('project-1', 'note-2'));
    expect(useNotes.getState().notes.map((n) => n.title)).toEqual(['First']);
    vi.unstubAllGlobals();
  });

  it('saves an answer under the question it replied to', async () => {
    const project = { id: 'project-1', name: 'P' } as Project;
    const question: Message = {
      id: 'm1', conversation_id: 'c', role: 'user', content: 'Why is the sky blue?', created_at: '',
    };
    const answer: Message = {
      id: 'm2', conversation_id: 'c', role: 'assistant', content: 'Scattering [1].', created_at: '',
    };
    useStore.setState({ currentProject: project, messages: [question, answer] });
    useNotes.setState({ projectId: 'project-1', notes: [] });
    const create = vi.spyOn(api, 'createNote').mockResolvedValue(
      note({ origin: 'answer', source_message_id: 'm2' }));

    render(<SaveToNoteButton message={answer} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save to note' }));

    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();
    expect(create).toHaveBeenCalledWith(
      'project-1', { title: 'Why is the sky blue?', source_message_id: 'm2' });
    expect(useNotes.getState().notes).toHaveLength(1);
  });
});
