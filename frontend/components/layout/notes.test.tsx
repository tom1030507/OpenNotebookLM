// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NotesSection from './NotesSection';
import SaveToNoteButton from '../chat/SaveToNoteButton';
import useStore from '@/store/useStore';
import useNotes from '@/store/useNotes';
import api from '@/lib/api';
import type { Document, Message, MindMap, Note, Project, VideoSummary } from '@/lib/api';

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
  beforeEach(() => {
    useStore.setState({
      currentProject: { id: 'project-1', name: 'P', role: 'owner' } as Project,
    });
  });

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

  it('offers source conversion for a note and for all unlinked notes', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({})]);

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^First/ }));

    expect(screen.getByRole('button', { name: 'Use as source' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Convert all notes' })).toBeTruthy();
  });

  it('downloads one note or all project notes in the selected format', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({})]);
    const exportNote = vi.spyOn(api, 'exportNote').mockResolvedValue(new Blob(['note']));
    const exportProject = vi.spyOn(api, 'exportProjectNotes')
      .mockResolvedValue(new Blob(['notes']));
    const createObjectURL = vi.fn(() => 'blob:notes');
    const revokeObjectURL = vi.fn();
    const clickDownload = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    render(<NotesSection projectId="project-1" />);
    fireEvent.change(await screen.findByRole(
      'combobox', { name: 'Export note First as' },
    ), { target: { value: 'pdf' } });
    await waitFor(() => expect(exportNote).toHaveBeenCalledWith(
      'project-1', 'note-1', 'pdf',
    ));

    fireEvent.change(screen.getByRole(
      'combobox', { name: 'Export all notes as' },
    ), { target: { value: 'docx' } });
    await waitFor(() => expect(exportProject).toHaveBeenCalledWith(
      'project-1', 'docx',
    ));
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(clickDownload).toHaveBeenCalledTimes(2);
  });

  it('converts one note and marks it as a source', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({})]);
    const refresh = vi.fn().mockImplementation(async () => {
      useStore.setState({ documents: [{ id: 'doc-1' } as Document] });
    });
    useStore.setState({ fetchDocuments: refresh });
    const convert = vi.spyOn(api, 'convertNoteToSource').mockResolvedValue({
      note_id: 'note-1', doc_id: 'doc-1', status: 'queued',
    });

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^First/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Use as source' }));

    await waitFor(() => expect(convert).toHaveBeenCalledWith('project-1', 'note-1'));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith('project-1'));
    expect(await screen.findByText('Used as a source')).toBeTruthy();
    expect(useNotes.getState().notes[0].source_document_id).toBe('doc-1');
  });

  it('converts all eligible notes in one request', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([
      note({ id: 'note-1' }),
      note({ id: 'note-2', title: 'Second' }),
    ]);
    const refresh = vi.fn().mockImplementation(async () => {
      useStore.setState({ documents: [
        { id: 'doc-1' } as Document,
        { id: 'doc-2' } as Document,
      ] });
    });
    useStore.setState({ fetchDocuments: refresh });
    const convertAll = vi.spyOn(api, 'convertAllNotesToSources').mockResolvedValue({
      sources: [
        { note_id: 'note-1', doc_id: 'doc-1', status: 'queued' },
        { note_id: 'note-2', doc_id: 'doc-2', status: 'queued' },
      ],
      failed_note_ids: [],
    });

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Convert all notes' }));

    await waitFor(() => expect(convertAll).toHaveBeenCalledWith('project-1'));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith('project-1'));
    expect(useNotes.getState().notes.map((saved) => saved.source_document_id))
      .toEqual(['doc-1', 'doc-2']);
  });

  it('offers to refresh a linked source after saving note edits', async () => {
    const linked = note({ source_document_id: 'doc-1' });
    vi.spyOn(api, 'listNotes').mockResolvedValue([linked]);
    useStore.setState({ documents: [{ id: 'doc-1' } as Document] });
    const refresh = vi.fn().mockResolvedValue(undefined);
    useStore.setState({ fetchDocuments: refresh });
    const update = vi.spyOn(api, 'updateNote').mockResolvedValue({
      ...linked, content: 'Updated body',
    });
    const convert = vi.spyOn(api, 'convertNoteToSource').mockResolvedValue({
      note_id: linked.id, doc_id: 'doc-1', status: 'queued',
    });
    vi.stubGlobal('confirm', () => true);

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^First/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Note content'), {
      target: { value: 'Updated body' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

    await waitFor(() => expect(update).toHaveBeenCalled());
    await waitFor(() => expect(convert).toHaveBeenCalledWith('project-1', linked.id));
  });

  it('offers conversion again after the linked source is deleted', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({ source_document_id: 'doc-1' })]);
    useStore.setState({ documents: [], loadingDocuments: false });

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^First/ }));

    expect(screen.queryByText('Used as a source')).toBeNull();
    expect(screen.getByRole('button', { name: 'Use as source' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Convert all notes' })).toBeTruthy();
  });

  it('saves an answer under the question it replied to', async () => {
    const project = { id: 'project-1', name: 'P', role: 'owner' } as Project;
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
    useStore.setState({ currentProject: { id: 'project-1', name: 'P', role: 'owner' } as Project });
    const saved = note({ origin: 'answer', source_message_id: 'm2' });
    vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);
    await act(async () => useNotes.getState().load('project-1'));
    const create = vi.spyOn(api, 'createNote');

    render(<SaveToNoteButton message={answer} />);

    expect(screen.getByRole('button', { name: 'Saved to notes' })).toBeTruthy();
    expect(create).not.toHaveBeenCalled();
  });

  it.each([
    ['legacy', [
      '- [1] Physics handbook, page 12',
      '  > At sea level, water boils at 100 C.',
      '- [2] Unused source, page 1',
      '- [5] Physics handbook, page 13',
      '  > The pressure changes the boiling point.',
      '- Older source, page 3',
      '  > Older passage.',
    ].join('\n')],
    ['grouped', [
      '- Physics handbook',
      '  - [1], page 12',
      '    > At sea level, water boils at 100 C.',
      '  - [5], page 13',
      '    > The pressure changes the boiling point.',
      '- Unused source',
      '  - [2], page 1',
      '- Older source',
      '  - Passage, page 3',
      '    > Older passage.',
    ].join('\n')],
  ])('renders saved answer citations as previews from %s source lists', async (_format, sourceList) => {
    const saved = note({
      origin: 'answer',
      content: `Scattering [Source 1] and [Source 5].\n\n**Sources**\n\n${sourceList}`,
    });
    vi.spyOn(api, 'listNotes').mockResolvedValue([saved]);

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^First/ }));

    expect(screen.getAllByRole('button', { name: 'Preview source 1' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: 'Preview source 2' })).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Preview source 5' })).toBeNull();
    expect(screen.getAllByText('Physics handbook')).toHaveLength(1);
    expect(screen.queryByText('Unused source')).toBeNull();
    expect(screen.getByText('Older passage.')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview source 2' })[0]);
    expect(screen.getByRole('tooltip').textContent).toContain('The pressure changes the boiling point.');
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

    useStore.setState({ currentProject: { id: 'project-1', name: 'P', role: 'owner' } as Project });
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

  it('renders saved report citations as source previews', async () => {
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({
      title: 'Saved report',
      origin: 'studio',
      studio_kind: 'report',
      content: [
        '# Report',
        '',
        'Rainfall increased [Source 1].',
        '',
        '**Sources**',
        '',
        '- Rainfall study',
        '  - [1]',
        '    > Rainfall increased in the western region.',
      ].join('\n'),
    })]);

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /Saved report/ }));

    const previews = await screen.findAllByRole('button', { name: 'Preview source 1' });
    expect(previews).toHaveLength(2);
    fireEvent.click(previews[0]);
    expect((await screen.findByRole('tooltip')).textContent)
      .toContain('Rainfall increased in the western region.');
  });

  it('lets viewers read notes but hides every note write control', async () => {
    useStore.setState({
      currentProject: { id: 'project-1', name: 'P', role: 'viewer' } as Project,
    });
    vi.spyOn(api, 'listNotes').mockResolvedValue([note({ title: 'Shared note' })]);

    render(<NotesSection projectId="project-1" />);
    fireEvent.click(await screen.findByRole('button', { name: /^Shared note/ }));

    expect(screen.getByText('Body')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'New note' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('does not offer viewers a way to save a private answer into shared notes', () => {
    const answer: Message = {
      id: 'm2', conversation_id: 'c', role: 'assistant', content: 'Private answer.', created_at: '',
    };
    useStore.setState({
      currentProject: { id: 'project-1', name: 'P', role: 'viewer' } as Project,
      messages: [answer],
    });
    useNotes.setState({ projectId: 'project-1', notes: [] });

    render(<SaveToNoteButton message={answer} />);

    expect(screen.queryByRole('button', { name: 'Save to note' })).toBeNull();
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
