// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { Document, Project, VideoSummary } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-20T00:00:00Z',
  updated_at: '2026-08-20T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
};

const source: Document = {
  id: 'doc-1',
  name: 'Only source',
  type: 'url',
  url: 'https://example.com',
  meta: {},
  status: 'ready',
  created_at: '2026-08-20T00:00:00Z',
  updated_at: '2026-08-20T00:00:00Z',
  chunk_count: 4,
};

const summary = (modelUsed = 'test-model'): VideoSummary => ({
  project_id: 'project-1',
  project_name: 'Research notes',
  generated_at: '2026-08-20T00:00:00Z',
  model_used: modelUsed,
  scene_count: 3,
  estimated_seconds: 20,
  scenes: [
    {
      id: 'title',
      kind: 'title',
      headline: 'Research notes',
      bullets: ['1 source', 'Generated 20 August 2026'],
      narration: 'This is a video summary of the project Research notes.',
      document_id: null,
      source_label: null,
    },
    {
      id: 'doc-1',
      kind: 'source',
      headline: 'Rainfall is rising',
      bullets: ['Rainfall', 'Glaciers'],
      narration: 'This source is about rainfall and glaciers.',
      document_id: 'doc-1',
      source_label: 'Only source',
    },
    {
      id: 'closing',
      kind: 'closing',
      headline: 'What this project covers',
      bullets: ['Rainfall is rising'],
      narration: 'That is Research notes, covering 1 source.',
      document_id: null,
      source_label: null,
    },
  ],
});

const initialState = useStore.getState();

interface Utterance {
  text: string;
  onend?: () => void;
  onerror?: (event: { error: string }) => void;
}

/**
 * Stub the browser's speech synthesis, returning the queue of utterances so a
 * test can end one and watch the player move on.
 *
 * @param cancelError Error a `cancel()` reports on whatever is being spoken, as
 *   Chrome does. Omit to have cancel say nothing.
 */
function installSpeech(cancelError?: string) {
  const spoken: Utterance[] = [];

  class U {
    text: string;
    rate = 1;
    onend?: () => void;
    onerror?: (event: { error: string }) => void;
    constructor(text: string) { this.text = text; }
  }

  vi.stubGlobal('SpeechSynthesisUtterance', U);
  vi.stubGlobal('speechSynthesis', {
    speak: (utterance: Utterance) => spoken.push(utterance),
    cancel: () => {
      if (!cancelError) return;
      spoken.forEach((utterance) => utterance.onerror?.({ error: cancelError }));
    },
    speaking: false,
  });

  return spoken;
}

const openVideoSummary = async () => {
  render(<StudioPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Video summary' }));
  return screen.findByRole('dialog');
};

/** End the utterance the player is waiting on, the way the browser does. */
const finishSpeaking = async (utterance: Utterance) => {
  await act(async () => {
    utterance.onend?.();
  });
};

beforeEach(() => {
  useStore.setState({
    currentProject: project,
    projects: [project],
    documents: [source],
  });
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:video-summary'),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.setState(initialState, true);
});

describe('Studio video summary', () => {
  it('opens the script for the selected project', async () => {
    installSpeech();
    const spy = vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1'));
    expect(screen.getByText('Research notes video summary')).toBeTruthy();
  });

  it('shows the first scene on the slide', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();

    expect(await screen.findByText('Research notes')).toBeTruthy();
    expect(screen.getByText('1 source')).toBeTruthy();
    expect(screen.getByText('Scene 1 of 3')).toBeTruthy();
  });

  it('shows the narration on screen as well as speaking it', async () => {
    // Without this the summary is unusable to anyone who cannot hear it, and
    // unusable in any browser that cannot speak.
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();

    expect(await screen.findByText(/This is a video summary of the project/)).toBeTruthy();
  });

  it('starts reading the first scene out', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();

    await waitFor(() => expect(spoken).toHaveLength(1));
    expect(spoken[0].text).toContain('This is a video summary');
  });

  it('advances to the next scene when the voice finishes', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    await waitFor(() => expect(spoken).toHaveLength(1));
    await finishSpeaking(spoken[0]);

    expect(await screen.findByText('Rainfall is rising')).toBeTruthy();
    expect(screen.getByText('Scene 2 of 3')).toBeTruthy();
    await waitFor(() => expect(spoken).toHaveLength(2));
  });

  it('cites the source a scene came from', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    await waitFor(() => expect(spoken).toHaveLength(1));
    await finishSpeaking(spoken[0]);

    expect(await screen.findByText('Source: Only source')).toBeTruthy();
  });

  it('stops at the end instead of looping', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    await waitFor(() => expect(spoken).toHaveLength(1));
    await finishSpeaking(spoken[0]);
    await waitFor(() => expect(spoken).toHaveLength(2));
    await finishSpeaking(spoken[1]);
    await waitFor(() => expect(spoken).toHaveLength(3));
    await finishSpeaking(spoken[2]);

    expect(await screen.findByRole('button', { name: /^Play/ })).toBeTruthy();
    expect(screen.getByText('Scene 3 of 3')).toBeTruthy();
  });

  it('steps between scenes on request', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    const next = await screen.findByRole('button', { name: 'Next scene' });
    expect((screen.getByRole('button', { name: 'Previous scene' }) as HTMLButtonElement)
      .disabled).toBe(true);

    fireEvent.click(next);
    expect(await screen.findByText('Scene 2 of 3')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Previous scene' }));
    expect(await screen.findByText('Scene 1 of 3')).toBeTruthy();
  });

  it('will not step past the last scene', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    fireEvent.click(await screen.findByRole('button', { name: 'Next scene' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next scene' }));

    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Next scene' }) as HTMLButtonElement).disabled,
    ).toBe(true));
  });

  it('pauses without moving on', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    await waitFor(() => expect(spoken).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: /^Pause/ }));

    expect(await screen.findByRole('button', { name: /^Play/ })).toBeTruthy();
    expect(screen.getByText('Scene 1 of 3')).toBeTruthy();
  });

  it('does not skip a scene when the browser reports the pause as an error', async () => {
    // Chrome answers cancel() by firing onerror('interrupted') on whatever was
    // being spoken, and `speakText` treats that as the reading ending. Without
    // retiring the run, pausing would advance the slide.
    const spoken = installSpeech('interrupted');
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    await waitFor(() => expect(spoken).toHaveLength(1));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Pause/ }));
    });

    expect(screen.getByText('Scene 1 of 3')).toBeTruthy();
  });

  it('plays silently where the browser cannot speak', async () => {
    // No speechSynthesis stubbed at all: jsdom has none of its own.
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();

    expect(await screen.findByText(/cannot read the narration out/i)).toBeTruthy();
    expect(screen.getByText('Scene 1 of 3')).toBeTruthy();
  });

  it('says when the narration came from document structure rather than a model', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary('fallback'));

    await openVideoSummary();

    expect(await screen.findByText(/document structure/i)).toBeTruthy();
    expect(screen.queryByText(/fallback/i)).toBeNull();
  });

  it('names the model that wrote the narration', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary('claude-opus'));

    await openVideoSummary();

    expect(await screen.findByText(/claude-opus/)).toBeTruthy();
  });

  it('downloads the script as Markdown', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());
    const downloads: string[] = [];
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const element = realCreate(tag) as HTMLElement;
      if (tag === 'a') {
        (element as HTMLAnchorElement).click = () =>
          downloads.push((element as HTMLAnchorElement).download);
      }
      return element;
    });

    await openVideoSummary();
    fireEvent.click(await screen.findByRole('button', { name: /download/i }));

    await waitFor(() => expect(downloads).toEqual(['Research notes video summary.md']));
  });

  it('closes without leaving the action stuck', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    await openVideoSummary();
    fireEvent.click(await screen.findByRole('button', { name: /close/i }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(
      (screen.getByRole('button', { name: 'Video summary' }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it('renders the dialog outside the Studio panel', async () => {
    // The mobile Studio drawer slides in with a transform, which makes it the
    // containing block for `position: fixed`. A dialog rendered inside it is
    // trapped at the drawer's width instead of covering the screen.
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockResolvedValue(summary());

    const dialog = await openVideoSummary();

    expect(dialog.closest('aside')).toBeNull();
  });

  it('keeps the action unavailable without a project', () => {
    useStore.setState({ currentProject: null, projects: [] });
    render(<StudioPanel />);

    expect(
      (screen.getByRole('button', { name: /^Video summary/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('plays a summary of a source added since the project loaded', () => {
    // The project's own count was read when the project list arrived and says
    // nothing about the source uploaded a moment ago.
    useStore.setState({
      currentProject: { ...project, document_count: 0 },
      documents: [source],
    });
    render(<StudioPanel />);

    expect(
      (screen.getByRole('button', { name: 'Video summary' }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.getByText('Watch a walkthrough of this project')).toBeTruthy();
  });

  it('will not play a summary once the last source is removed', () => {
    // Two empty slides are not worth playing, however many sources the
    // project's stale count still claims.
    useStore.setState({
      currentProject: { ...project, document_count: 3 },
      documents: [],
    });
    render(<StudioPanel />);

    expect(
      (screen.getByRole('button', { name: 'Video summary' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText('Add a source first')).toBeTruthy();
  });

  it('does not call a project empty while its sources are still loading', () => {
    // An empty list mid-fetch means "not known yet", not "nothing to play".
    useStore.setState({ documents: [], loadingDocuments: true });
    render(<StudioPanel />);

    expect(
      (screen.getByRole('button', { name: 'Video summary' }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.queryByText('Add a source first')).toBeNull();
  });

  it('surfaces a failure instead of opening an empty player', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectVideoSummary').mockRejectedValue(new Error('nope'));

    render(<StudioPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Video summary' }));

    expect(await screen.findByText(/video summary could not be prepared/i)).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Video summary' }) as HTMLButtonElement).disabled,
    ).toBe(false));
  });
});
