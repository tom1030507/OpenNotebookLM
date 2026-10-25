// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import type { Conversation, Project } from '@/lib/api';
import api from '@/lib/api';
import useStore from '@/store/useStore';
import ConversationList from './ConversationList';

const project: Project = {
  id: 'project-1',
  name: 'Project one',
  description: null,
  meta_json: {},
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  document_count: 0,
  conversation_count: 1,
  role: 'owner',
};

const conversation: Conversation = {
  id: 'conversation-1',
  project_id: project.id,
  title: 'Existing chat',
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  message_count: 1,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});

describe('ConversationList', () => {
  it('does not create a blank conversation when New Conversation is clicked repeatedly', () => {
    const createConversation = vi.spyOn(api, 'createConversation').mockResolvedValue({
      ...conversation,
      id: 'conversation-new',
      title: 'New Conversation',
      message_count: 0,
    });
    useStore.setState({
      currentProject: project,
      currentConversation: conversation,
      conversations: [conversation],
    });
    render(<ConversationList />);
    const newConversationButton = screen.getByRole('button', { name: 'New Conversation' });

    fireEvent.click(newConversationButton);
    fireEvent.click(newConversationButton);

    expect(createConversation).not.toHaveBeenCalled();
    expect(useStore.getState().currentConversation).toBeNull();
    expect(useStore.getState().conversations).toEqual([conversation]);
  });
});
