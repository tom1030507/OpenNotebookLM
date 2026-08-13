// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StudioPanel from './StudioPanel';
import useStore from '@/store/useStore';
import api from '@/lib/api';
import type { Project } from '@/lib/api';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 2,
  conversation_count: 1,
};

const initialState = useStore.getState();

interface Utterance { text: string; onend?: () => void; onerror?: (e: { error: string }) => void }

function installSpeech() {
  const spoken: Utterance[] = [];
  class U {
    text: string;
    rate = 1;
    onend?: () => void;
    onerror?: (e: { error: string }) => void;
    constructor(text: string) { this.text = text; }
  }
  vi.stubGlobal('SpeechSynthesisUtterance', U);
  vi.stubGlobal('speechSynthesis', {
    speak: (u: Utterance) => spoken.push(u),
    cancel: () => {},
    speaking: false,
  });
  return spoken;
}

const summary = '# Research notes\n\n- **Example Domain** overview';

beforeEach(() => {
  useStore.setState({ currentProject: project, projects: [project] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.setState(initialState, true);
});

describe('Studio audio summary', () => {
  it('reads the project summary aloud with the Markdown stripped', async () => {
    const spoken = installSpeech();
    const spy = vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    const audio = screen.getByRole('button', { name: 'Audio summary' });
    expect((audio as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(audio);

    await waitFor(() => expect(spy).toHaveBeenCalledWith('project-1'));
    await waitFor(() => expect(spoken).toHaveLength(1));
    expect(spoken[0].text).toContain('Research notes');
    expect(spoken[0].text).toContain('Example Domain');
    expect(spoken[0].text).not.toMatch(/[#*]/);
  });

  it('offers a stop control while speaking and returns to play when finished', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    const stop = await screen.findByRole('button', { name: 'Stop audio summary' });
    expect(stop).toBeTruthy();

    spoken[0].onend?.();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Stop audio summary' })).toBeNull();
  });

  it('stops playback when the stop control is used', async () => {
    installSpeech();
    const cancel = vi.fn();
    vi.stubGlobal('speechSynthesis', { speak: () => {}, cancel, speaking: true });
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    const stop = await screen.findByRole('button', { name: 'Stop audio summary' });
    fireEvent.click(stop);

    await waitFor(() => expect(cancel).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());
  });

  it('explains itself when the browser cannot speak', () => {
    vi.stubGlobal('speechSynthesis', undefined);
    render(<StudioPanel />);

    const audio = screen.getByRole('button', { name: /^Audio summary/ });
    expect((audio as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/not supported in this browser/i)).toBeTruthy();
  });

  it('surfaces a summary failure without leaving the control stuck', async () => {
    installSpeech();
    vi.spyOn(api, 'fetchProjectSummaryText').mockRejectedValue(new Error('nope'));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));

    expect(await screen.findByText(/could not be read out/i)).toBeTruthy();
    await waitFor(() => expect(
      (screen.getByRole('button', { name: 'Audio summary' }) as HTMLButtonElement).disabled,
    ).toBe(false));
  });

  it('keeps audio unavailable without a project', () => {
    installSpeech();
    useStore.setState({ currentProject: null, projects: [] });
    render(<StudioPanel />);

    expect((screen.getByRole('button', { name: /^Audio summary/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
