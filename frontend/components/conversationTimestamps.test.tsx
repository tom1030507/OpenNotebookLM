// @vitest-environment jsdom

/**
 * The backend stores naive UTC timestamps. A value that reaches the client
 * without a timezone designator — `2026-08-13T16:29:50` — is parsed by
 * `new Date(...)` as *local* time, so every timestamp is skewed by the viewer's
 * UTC offset: a conversation created seconds ago reads as "about 8 hours ago"
 * and drops into the wrong date-group header.
 *
 * These tests pin the viewer's timezone rather than trusting the machine's, and
 * pick an instant where the local date and the UTC date differ, so a
 * mis-parsed timestamp cannot accidentally land in the right group.
 */

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ConversationList from './ConversationList';
import useStore from '@/store/useStore';
import type { Conversation, Project } from '@/lib/api';

// 00:30 on 14 August in Asia/Taipei (UTC+8) — the local day is already ahead of
// the UTC day, which is exactly when a local-time misreading changes the group.
const NOW_UTC = '2026-08-13T16:30:00Z';
const VIEWER_TIMEZONE = 'Asia/Taipei';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 0,
  conversation_count: 1,
};

function conversationCreatedAt(created_at: string): Conversation {
  return {
    id: 'conversation-1',
    project_id: project.id,
    title: 'Fresh chat',
    created_at,
    updated_at: created_at,
    message_count: 0,
  };
}

let originalTimezone: string | undefined;

beforeEach(() => {
  originalTimezone = process.env.TZ;
  process.env.TZ = VIEWER_TIMEZONE;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(NOW_UTC));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  process.env.TZ = originalTimezone;
  useStore.getState().resetForTests();
});

function renderWith(created_at: string) {
  useStore.setState({
    currentProject: project,
    conversations: [conversationCreatedAt(created_at)],
    currentConversation: null,
  });

  render(<ConversationList />);
}

describe('conversation timestamps for a viewer outside UTC', () => {
  it('reads a designator-less timestamp as UTC, not as local time', () => {
    // What already-stored rows look like: the naive UTC instant 10 seconds ago.
    renderWith('2026-08-13T16:29:50');

    expect(screen.getByText(/less than a minute ago/)).toBeTruthy();
  });

  it('groups a designator-less just-now timestamp under Today', () => {
    renderWith('2026-08-13T16:29:50');

    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('Today');
  });

  it('reads a UTC-designated timestamp as UTC', () => {
    // What the fixed API emits.
    renderWith('2026-08-13T16:29:50Z');

    expect(screen.getByText(/less than a minute ago/)).toBeTruthy();
    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('Today');
  });

  it('reads an offset-designated timestamp at its stated offset', () => {
    // Same instant, written in the viewer's own offset: still just now.
    renderWith('2026-08-14T00:29:50+08:00');

    expect(screen.getByText(/less than a minute ago/)).toBeTruthy();
    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('Today');
  });

  it('still groups a genuinely older conversation away from Today', () => {
    // Noon yesterday in the viewer's zone, so the local day really is the
    // previous one.
    renderWith('2026-08-13T04:00:00Z');

    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('Yesterday');
  });
});
