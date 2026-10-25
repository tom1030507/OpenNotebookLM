// @vitest-environment jsdom

import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import api, { type Project } from '@/lib/api';
import useStore from '@/store/useStore';
import { FollowUpQuestions, ProjectOverview } from './SuggestedQuestions';

const project: Project = {
  id: 'project-1',
  name: 'Untitled notebook',
  description: null,
  meta_json: {},
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
  role: 'owner',
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});

describe('ProjectOverview', () => {
  it('shows the overview, sends a clicked question and applies the generated title', async () => {
    useStore.setState({ projects: [project], currentProject: project });
    vi.spyOn(api, 'fetchProjectOverview').mockResolvedValue({
      project_name: 'Glacier Retreat',
      overview: 'These sources describe how glaciers shrink.',
      questions: ['Why do glaciers retreat?', 'How fast?', 'Where?'],
    });
    const onAsk = vi.fn();

    render(<ProjectOverview projectId="project-1" readySourceKey="doc-1" onAsk={onAsk} />);

    expect(await screen.findByText('These sources describe how glaciers shrink.')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'How fast?' }));
    expect(onAsk).toHaveBeenCalledWith('How fast?');
    expect(useStore.getState().currentProject?.name).toBe('Glacier Retreat');
    expect(useStore.getState().projects[0].name).toBe('Glacier Retreat');
  });

  it('renders nothing when no overview was generated', async () => {
    const fetchOverview = vi.spyOn(api, 'fetchProjectOverview').mockResolvedValue({
      project_name: 'Notes',
      overview: null,
      questions: [],
    });

    const { container } = render(
      <ProjectOverview projectId="project-1" readySourceKey="doc-1" onAsk={vi.fn()} />,
    );

    await waitFor(() => expect(fetchOverview).toHaveBeenCalledWith('project-1'));
    expect(container.innerHTML).toBe('');
  });
});

describe('FollowUpQuestions', () => {
  it('offers the follow-ups for the latest answer', async () => {
    const fetchFollowUps = vi.spyOn(api, 'fetchFollowUpQuestions')
      .mockResolvedValue(['What next?', 'And then?']);
    const onAsk = vi.fn();

    render(<FollowUpQuestions conversationId="c1" messageId="m2" onAsk={onAsk} />);

    await userEvent.click(await screen.findByRole('button', { name: 'And then?' }));
    expect(fetchFollowUps).toHaveBeenCalledWith('c1');
    expect(onAsk).toHaveBeenCalledWith('And then?');
  });

  it('disables follow-up questions when no source is selected', async () => {
    vi.spyOn(api, 'fetchFollowUpQuestions').mockResolvedValue(['What next?']);

    render(
      <FollowUpQuestions
        conversationId="c1"
        messageId="m2"
        disabled
        onAsk={vi.fn()}
      />,
    );

    expect((await screen.findByRole('button', { name: 'What next?' }) as HTMLButtonElement).disabled)
      .toBe(true);
  });
});
