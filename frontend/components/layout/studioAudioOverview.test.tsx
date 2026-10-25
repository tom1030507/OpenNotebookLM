// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api, { type AudioOverview, type Project } from '@/lib/api';
import useStore from '@/store/useStore';
import StudioPanel from './StudioPanel';

const project: Project = {
  id: 'audio-project',
  name: 'Climate notes',
  description: null,
  meta_json: {},
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  document_count: 2,
  conversation_count: 0,
  role: 'owner',
};
const NativeURL = globalThis.URL;

const readyOverview = (id = 'saved-audio'): AudioOverview => ({
  id,
  status: 'ready',
  options: { format: 'deep_dive', length: 'default' },
  script: [
    { speaker: 'A', text: 'The first host explains the source evidence.' },
    { speaker: 'B', text: 'The second host connects the findings.' },
  ],
  duration_seconds: 18,
  error: null,
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:10Z',
  started_at: '2026-10-25T00:00:01Z',
  completed_at: '2026-10-25T00:00:10Z',
});

beforeEach(() => {
  useStore.setState({
    currentProject: project,
    projects: [project],
    documents: [
      { id: 'source-a', name: 'Source A', type: 'text', isOwnedByCaller: true, status: 'ready', meta: {}, created_at: '', updated_at: '', chunk_count: 1 },
      { id: 'source-b', name: 'Source B', type: 'text', isOwnedByCaller: true, status: 'ready', meta: {}, created_at: '', updated_at: '', chunk_count: 1 },
    ],
    deselectedSources: { 'audio-project': ['source-b'] },
  });
  const AudioURL = class extends NativeURL {};
  Object.assign(AudioURL, {
    createObjectURL: vi.fn(() => 'blob:audio-overview'),
    revokeObjectURL: vi.fn(),
  });
  vi.stubGlobal('URL', AudioURL);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.getState().resetForTests();
});

describe('Studio audio overview', () => {
  it('sends selected sources and options, polls status, and shows both hosts', async () => {
    const queued: AudioOverview = {
      ...readyOverview('new-audio'),
      status: 'queued',
      script: [],
      duration_seconds: null,
      completed_at: null,
    };
    vi.spyOn(api, 'listAudioOverviews').mockResolvedValue({ enabled: true, items: [] });
    vi.spyOn(api, 'createAudioOverview').mockResolvedValue(queued);
    vi.spyOn(api, 'getAudioOverview').mockResolvedValue(readyOverview('new-audio'));
    vi.spyOn(api, 'fetchAudioOverviewFile').mockResolvedValue(new Blob(['audio']));
    const legacySpeech = vi.spyOn(api, 'fetchProjectSummaryText');
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Customize Audio summary' }));
    fireEvent.change(screen.getByLabelText('Focus (optional)'), { target: { value: 'methods' } });
    fireEvent.change(screen.getByLabelText('Audience'), { target: { value: 'beginner' } });
    fireEvent.change(screen.getByLabelText('Length'), { target: { value: 'long' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    await screen.findByRole('dialog', { name: 'Audio summary' });
    const generate = screen.getByRole('button', { name: 'Generate audio summary' });
    await waitFor(() => expect((generate as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'debate' } });
    fireEvent.click(generate);

    await waitFor(() => expect(api.createAudioOverview).toHaveBeenCalledWith('audio-project', {
      format: 'debate',
      length: 'long',
      focus: 'methods',
      audience: 'beginner',
      document_ids: ['source-a'],
    }));
    await waitFor(() => expect(api.getAudioOverview).toHaveBeenCalledWith('audio-project', 'new-audio'), {
      timeout: 3000,
    });
    expect(await screen.findByText('The first host explains the source evidence.')).toBeTruthy();
    expect(screen.getByText('The second host connects the findings.')).toBeTruthy();
    expect(await screen.findByLabelText('Audio overview playback')).toBeTruthy();
    expect(legacySpeech).not.toHaveBeenCalled();
  });

  it('loads saved audio and its transcript when the dialog is reopened', async () => {
    vi.spyOn(api, 'listAudioOverviews').mockResolvedValue({ enabled: true, items: [readyOverview()] });
    vi.spyOn(api, 'fetchAudioOverviewFile').mockResolvedValue(new Blob(['saved audio']));
    render(<StudioPanel />);

    fireEvent.click(screen.getByRole('button', { name: 'Audio summary' }));

    expect(await screen.findByText('The first host explains the source evidence.')).toBeTruthy();
    expect(screen.getByText('The second host connects the findings.')).toBeTruthy();
    expect(await screen.findByLabelText('Audio overview playback')).toBeTruthy();
    expect(api.fetchAudioOverviewFile).toHaveBeenCalledWith('audio-project', 'saved-audio');
  });
});
