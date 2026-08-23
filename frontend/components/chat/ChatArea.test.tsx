// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api, {
  type Conversation,
  type Document,
  type Message,
  type Project,
} from '@/lib/api';
import useStore from '@/store/useStore';
import ChatArea from './ChatArea';


const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-21T00:00:00Z',
  updated_at: '2026-08-21T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
};

const readyDocument: Document = {
  id: 'document-1',
  name: 'Ready source',
  type: 'text',
  meta: {},
  status: 'ready',
  created_at: '2026-08-21T00:00:00Z',
  updated_at: '2026-08-21T00:00:00Z',
  chunk_count: 1,
};


const conversation = (id: string, projectId: string): Conversation => ({
  id,
  project_id: projectId,
  title: 'Research chat',
  created_at: '2026-08-21T00:00:00Z',
  updated_at: '2026-08-21T00:00:00Z',
  message_count: 0,
});


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}


beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});


describe('ChatArea', () => {
  it('keeps a failed question visible and retries it without duplicate messages', async () => {
    const question = 'What does this source say?';
    vi.spyOn(api, 'query')
      .mockRejectedValueOnce(new Error('Request failed'))
      .mockResolvedValueOnce({
        answer: '',
        sources: [],
        chunks_used: 0,
        model_used: null,
        usage: {},
        conversation_id: 'conversation-1',
      });
    vi.spyOn(api, 'getMessages').mockResolvedValue([
      {
        id: 'message-user',
        conversation_id: 'conversation-1',
        role: 'user',
        content: question,
        citations: [],
        created_at: '2026-08-23T00:00:00Z',
      },
      {
        id: 'message-assistant',
        conversation_id: 'conversation-1',
        role: 'assistant',
        content: 'It explains the source.',
        citations: [],
        created_at: '2026-08-23T00:00:01Z',
      },
    ]);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Request failed');
    expect(screen.getAllByText(question)).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Retry question' }));

    await waitFor(() => expect(screen.getByText('It explains the source.')).toBeTruthy());
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.getAllByText('It explains the source.')).toHaveLength(1);
  });

  it('refreshes persisted messages without resending a question after its query succeeds', async () => {
    const question = 'What does this source say?';
    const refreshedMessages = deferred<Message[]>();
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'It explains the source.',
      sources: [],
      chunks_used: 1,
      model_used: 'test-model',
      usage: {},
      conversation_id: 'conversation-1',
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Message refresh failed'))
      .mockReturnValueOnce(refreshedMessages.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The question was sent, but the conversation could not be refreshed.',
    );
    expect(screen.getByText(question, { selector: 'p' })).toBeTruthy();
    expect(query).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));

    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    expect(query).toHaveBeenCalledTimes(1);

    await act(async () => {
      refreshedMessages.resolve([
        {
          id: 'message-user',
          conversation_id: 'conversation-1',
          role: 'user',
          content: question,
          citations: [],
          created_at: '2026-08-23T00:00:00Z',
        },
        {
          id: 'message-assistant',
          conversation_id: 'conversation-1',
          role: 'assistant',
          content: 'It explains the source.',
          citations: [],
          created_at: '2026-08-23T00:00:01Z',
        },
      ]);
      await refreshedMessages.promise;
    });

    await waitFor(() => expect(screen.getByText('It explains the source.')).toBeTruthy());
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.getAllByText('It explains the source.')).toHaveLength(1);
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('keeps the first submitted question visible while its answer is pending', async () => {
    const queryRequest = deferred<void>();
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      messages: [],
      sendQuery: async () => queryRequest.promise,
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'What does this source say?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect(screen.queryByText('Add a source to get started')).toBeNull();
    expect(screen.getByText('What does this source say?')).not.toBeNull();

    await act(async () => {
      queryRequest.resolve();
      await queryRequest.promise;
    });
  });

  it('does not carry a pending question into another project', async () => {
    const queryRequest = deferred<void>();
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [],
      sendQuery: async () => queryRequest.promise,
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Question for the first project' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    const secondProject = { ...project, id: 'project-2', name: 'Other notes' };
    act(() => {
      useStore.setState({
        projects: [project, secondProject],
        currentProject: secondProject,
        documents: [{ ...readyDocument, id: 'document-2' }],
        currentConversation: null,
        messages: [],
      });
    });

    expect(screen.queryByText('Question for the first project')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false);

    await act(async () => {
      queryRequest.resolve();
      await queryRequest.promise;
    });
  });

  it('does not carry a pending question into another conversation', async () => {
    const queryRequest = deferred<void>();
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [],
      sendQuery: async () => queryRequest.promise,
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Question for the first conversation' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    act(() => {
      useStore.setState({
        currentConversation: conversation('conversation-2', project.id),
        messages: [],
      });
    });

    expect(screen.queryByText('Question for the first conversation')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false);

    await act(async () => {
      queryRequest.resolve();
      await queryRequest.promise;
    });
  });

  it('does not let an older request clear a newer pending question', async () => {
    const firstRequest = deferred<void>();
    const secondRequest = deferred<void>();
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [],
      sendQuery: async (query) => (
        query === 'First project question'
          ? firstRequest.promise
          : secondRequest.promise
      ),
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'First project question' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    const secondProject = { ...project, id: 'project-2', name: 'Other notes' };
    act(() => {
      useStore.setState({
        projects: [project, secondProject],
        currentProject: secondProject,
        documents: [{ ...readyDocument, id: 'document-2' }],
        currentConversation: conversation('conversation-2', secondProject.id),
        messages: [],
      });
    });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Second project question' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    await act(async () => {
      firstRequest.resolve();
      await firstRequest.promise;
    });

    expect(screen.getByText('Second project question')).not.toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);

    await act(async () => {
      secondRequest.resolve();
      await secondRequest.promise;
    });
  });

  it('does not bind a new-conversation query to a conversation selected by the user', async () => {
    const conversationCreation = deferred<void>();
    const answerRequest = deferred<void>();
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: null,
      messages: [],
      sendQuery: async (_query, _stream, onConversationReady) => {
        await conversationCreation.promise;
        onConversationReady?.('created-conversation');
        return answerRequest.promise;
      },
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Question that creates a conversation' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    act(() => {
      useStore.setState({
        currentConversation: conversation('existing-conversation', project.id),
        messages: [],
      });
    });

    expect(screen.queryByText('Question that creates a conversation')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false);

    await act(async () => {
      conversationCreation.resolve();
      await conversationCreation.promise;
    });
    expect(screen.queryByText('Question that creates a conversation')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false);

    await act(async () => {
      answerRequest.resolve();
      await answerRequest.promise;
    });
  });
});
