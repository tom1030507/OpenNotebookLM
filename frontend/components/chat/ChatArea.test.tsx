// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Conversation, Document, Project } from '@/lib/api';
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
  useStore.setState(useStore.getInitialState(), true);
});


describe('ChatArea', () => {
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
