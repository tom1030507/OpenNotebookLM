// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

/**
 * Mirrors the browser: cancel() reports the stop as an error on whatever is
 * being spoken, so a deliberate stop arrives through the failure path.
 */
function installSpeechReportingCancelAsError(error: string) {
  const spoken = installSpeech();
  const cancel = vi.fn(() => {
    spoken.forEach((utterance) => utterance.onerror?.({ error }));
  });
  vi.stubGlobal('speechSynthesis', {
    speak: (u: Utterance) => spoken.push(u),
    cancel,
    speaking: false,
  });
  return { spoken, cancel };
}

const summary = '# Research notes\n\n- **Example Domain** overview';

beforeEach(() => {
  useStore.setState({ currentProject: project, projects: [project] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.getState().resetForTests();
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

  it('treats a stop as deliberate rather than a playback failure', async () => {
    const { cancel } = installSpeechReportingCancelAsError('interrupted');
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop audio summary' }));

    await waitFor(() => expect(cancel).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/could not be read out/i)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Stop audio summary' })).toBeNull();
  });

  it('still reports a genuine synthesis failure', async () => {
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    await screen.findByRole('button', { name: 'Stop audio summary' });

    spoken[0].onerror?.({ error: 'synthesis-failed' });

    expect(await screen.findByText(/could not be read out/i)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());
  });

  it('leaves no error behind when a replay cancels the previous reading', async () => {
    const { spoken } = installSpeechReportingCancelAsError('canceled');
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    await screen.findByRole('button', { name: 'Stop audio summary' });

    // Stop, then play again: the second run must not inherit the first's cancel.
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio summary' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));

    await waitFor(() => expect(spoken).toHaveLength(2));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(await screen.findByRole('button', { name: 'Stop audio summary' })).toBeTruthy();
  });

  it('keeps the replacement reading playing when a stopped one reports its cancel late', async () => {
    // cancel() here never reports anything: the test decides when the browser
    // gets around to telling us the stopped reading was interrupted.
    const spoken = installSpeech();
    vi.spyOn(api, 'fetchProjectSummaryText').mockResolvedValue(summary);
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop audio summary' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Audio summary' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));
    await waitFor(() => expect(spoken).toHaveLength(2));
    await screen.findByRole('button', { name: 'Stop audio summary' });

    await act(async () => {
      spoken[0].onerror?.({ error: 'interrupted' });
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(screen.getByRole('button', { name: 'Stop audio summary' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
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
