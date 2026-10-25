// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ProjectAnalyticsDialog from './ProjectAnalyticsDialog';
import api from '@/lib/api';

const project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  document_count: 1,
  conversation_count: 1,
  role: 'owner' as const,
};

const analytics = {
  days: 7 as const,
  questions_by_day: [
    { date: '2026-10-25', question_count: 2 },
    { date: '2026-10-24', question_count: 0 },
  ],
  conversation_count: 1,
  top_cited_sources: [{
    document_id: 'document-1', title: 'Glacier report', citation_count: 3,
  }],
  ratings: { up: 1, down: 1, unrated: 0 },
  recent_down_rated_questions: [{
    question: 'Why is the glacier retreating?',
    answered_at: '2026-10-25T00:00:00Z',
  }],
  uncited_sources: [{ document_id: 'document-2', title: 'Climate notes' }],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ProjectAnalyticsDialog', () => {
  it('loads the default range, displays analytics, and reloads when the range changes', async () => {
    const getAnalytics = vi.spyOn(api, 'getProjectAnalytics').mockResolvedValue(analytics);

    render(
      <ProjectAnalyticsDialog project={project} isOpen onClose={() => undefined} />,
    );

    expect(await screen.findByRole('img', { name: 'Questions per day' })).toBeTruthy();
    expect(screen.getByText('Active conversations')).toBeTruthy();
    expect(screen.getByText('Glacier report')).toBeTruthy();
    expect(screen.getByText('Why is the glacier retreating?')).toBeTruthy();
    expect(getAnalytics).toHaveBeenCalledWith(project.id, 7);

    fireEvent.change(screen.getByLabelText('Date range'), { target: { value: '30' } });

    await waitFor(() => expect(getAnalytics).toHaveBeenLastCalledWith(project.id, 30));
  });

  it('shows an empty state when the selected period has no activity', async () => {
    vi.spyOn(api, 'getProjectAnalytics').mockResolvedValue({
      ...analytics,
      questions_by_day: [],
      conversation_count: 0,
      top_cited_sources: [],
      ratings: { up: 0, down: 0, unrated: 0 },
      recent_down_rated_questions: [],
      uncited_sources: [],
    });

    render(
      <ProjectAnalyticsDialog project={project} isOpen onClose={() => undefined} />,
    );

    expect(await screen.findByText('No activity in this period yet.')).toBeTruthy();
  });
});
