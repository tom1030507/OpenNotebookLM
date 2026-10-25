// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NotesSection from './NotesSection';
import SaveToNoteButton from '../chat/SaveToNoteButton';
import useStore from '@/store/useStore';
import useNotes from '@/store/useNotes';
import api from '@/lib/api';
import type { Message, MindMap, Note, Project, VideoSummary } from '@/lib/api';

const note = (fields: Partial<Note>): Note => ({
  id: 'note-1',
  project_id: 'project-1',
  title: 'First',
  content: 'Body',
  origin: 'manual',
  source_message_id: null,
  studio_kind: null,
  payload_json: null,
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  ...fields,
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

  it('shows an answer as saved when the notes list is loaded again', async () => {
    const answer: Message = {
      id: 'm2', conversation_id: 'c', role: 'assistant', content: 'Scattering [1].', created_at: '',
    };
    useStore.setState({ currentProject: { id: 'project-1', name: 'P' } as Project });
    const saved = note({ origin: 'answer', source_message_id: 'm2' });
    vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);
    await act(async () => useNotes.getState().load('project-1'));
    const create = vi.spyOn(api, 'createNote');

    render(<SaveToNoteButton message={answer} />);

    expect(screen.getByRole('button', { name: 'Saved to notes' })).toBeTruthy();
    expect(create).not.toHaveBeenCalled();
  });

  it('enables saving an answer again after its note is deleted', async () => {
    const answer: Message = {
      id: 'm2', conversation_id: 'c', role: 'assistant', content: 'Scattering [1].', created_at: '',
    };
    const saved = note({
      title: 'Why is the sky blue?', origin: 'answer', source_message_id: 'm2',
    });
    vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);
    const remove = vi.spyOn(api, 'deleteNote').mockResolvedValue();
    vi.stubGlobal('confirm', () => true);

    useStore.setState({ currentProject: { id: 'project-1', name: 'P' } as Project });
    render(<>
      <NotesSection projectId="project-1" />
      <SaveToNoteButton message={answer} />
    </>);

    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Why is the sky blue/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith('project-1', saved.id));
    expect(await screen.findByRole('button', { name: 'Save to note' })).toBeTruthy();
  });

  it.each(['mindmap', 'video_summary'] as const)(
    'allows deleting a saved Studio %s note', async (kind) => {
      const saved = note({
        title: `Saved ${kind}`, origin: 'studio', studio_kind: kind,
      });
      vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);
      const remove = vi.spyOn(api, 'deleteNote').mockResolvedValue();
      vi.stubGlobal('confirm', () => true);

      render(<NotesSection projectId="project-1" />);
      await screen.findByRole('button', { name: new RegExp(`^${saved.title}`) });
      fireEvent.click(screen.getByRole('button', { name: `Delete note ${saved.title}` }));

      await waitFor(() => expect(remove).toHaveBeenCalledWith('project-1', saved.id));
      expect(useNotes.getState().notes).toEqual([]);
    },
  );

  it('opens a saved Studio report as Markdown', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({
      title: 'Saved report', content: '# Report\n\nSaved findings.',
      origin: 'studio', studio_kind: 'report',
    })]);
    const generate = vi.spyOn(api, 'exportProjectSummary');

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /Saved report/ }));

    expect(screen.getByText('Saved findings.')).toBeTruthy();
    expect(screen.getByText('Studio · Report')).toBeTruthy();
    expect(generate).not.toHaveBeenCalled();
  });

  it.each(['mindmap', 'video_summary'] as const)(
    'reopens a saved %s without asking Studio to generate it again', async (kind) => {
      const map: MindMap = {
        project_id: 'project-1', project_name: 'Research',
        generated_at: '2026-10-25T00:00:00Z', model_used: 'fallback', node_count: 1,
        root: {
          id: 'root', label: 'Research', kind: 'project', detail: null,
          document_id: null, children: [],
        },
      };
      const summary: VideoSummary = {
        project_id: 'project-1', project_name: 'Research',
        generated_at: '2026-10-25T00:00:00Z', model_used: 'fallback',
        scene_count: 2, estimated_seconds: 2, scenes: [
          { id: 'title', kind: 'title', headline: 'Research', bullets: [],
            narration: 'Research.', document_id: null, source_label: null },
          { id: 'closing', kind: 'closing', headline: 'Summary', bullets: [],
            narration: 'That is the summary.', document_id: null, source_label: null },
        ],
      };
      const saved = kind === 'mindmap'
        ? note({ title: 'Map note', origin: 'studio', studio_kind: kind, payload_json: map })
        : note({ title: 'Video note', origin: 'studio', studio_kind: kind, payload_json: summary });
      vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);
      const generateMap = vi.spyOn(api, 'fetchProjectMindMap');
      const generateVideo = vi.spyOn(api, 'fetchProjectVideoSummary');

      render(<NotesSection projectId="project-1" />);
      fireEvent.click(await screen.findByRole('button', { name: new RegExp(`^${saved.title}`) }));

      const title = kind === 'mindmap' ? 'Research mind map' : 'Research video summary';
      expect(await screen.findByRole('dialog', { name: title })).toBeTruthy();
      expect(generateMap).not.toHaveBeenCalled();
      expect(generateVideo).not.toHaveBeenCalled();
    },
  );
});
