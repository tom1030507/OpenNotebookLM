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
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
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
  describe('mind map question handoff', () => {
    beforeEach(() => {
      useStore.setState({
        currentProject: project,
        documents: [readyDocument],
        currentConversation: conversation('conversation-1', project.id),
      });
    });

    it('prefills once and focuses after dialog cleanup without sending a question', async () => {
      const query = vi.spyOn(api, 'query');
      const createConversation = vi.spyOn(api, 'createConversation');
      const { unmount } = render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      const previousTrigger = document.createElement('button');
      document.body.append(previousTrigger);
      const composer = screen.getByRole('textbox') as HTMLTextAreaElement;

      act(() => useStore.getState().draftMindMapQuestion(project.id, 'Explain attention.'));
      previousTrigger.focus();

      await waitFor(() => expect(composer.value).toBe('Explain attention.'));
      await waitFor(() => expect(document.activeElement).toBe(composer));
      expect(useStore.getState().pendingMindMapQuestion).toBeNull();
      expect(query).not.toHaveBeenCalled();
      expect(createConversation).not.toHaveBeenCalled();

      unmount();
      previousTrigger.remove();
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
    });

    it('appends the topic question while preserving text already being composed', async () => {
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      const composer = screen.getByRole('textbox') as HTMLTextAreaElement;
      fireEvent.change(composer, { target: { value: 'Compare the two methods.' } });

      act(() => useStore.getState().draftMindMapQuestion(project.id, 'Explain attention.'));

      await waitFor(() => expect(composer.value).toBe('Compare the two methods.\n\nExplain attention.'));
    });

    it('ignores a stale project handoff without changing the composer', () => {
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      const composer = screen.getByRole('textbox') as HTMLTextAreaElement;
      fireEvent.change(composer, { target: { value: 'My current question' } });

      act(() => useStore.getState().draftMindMapQuestion('another-project', 'Private topic'));

      expect(composer.value).toBe('My current question');
    });

    it.each(['project', 'account'] as const)('clears a prefilled question across a batched %s change and return', async (boundary) => {
      vi.spyOn(api, 'getDocuments').mockResolvedValue([readyDocument]);
      vi.spyOn(api, 'getConversations').mockResolvedValue([]);
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      act(() => useStore.getState().draftMindMapQuestion(project.id, 'Private topic'));
      await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Private topic'));

      await act(async () => {
        if (boundary === 'account') {
          useStore.getState().clearAccountState();
        } else {
          useStore.getState().selectProject({ ...project, id: 'project-2' });
        }
        useStore.getState().selectProject(project);
      });

      expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
      expect(useStore.getState().pendingMindMapQuestion).toBeNull();
    });

    it('waits for the current send to finish before consuming the topic question', async () => {
      const request = deferred<Awaited<ReturnType<typeof api.query>>>();
      const query = vi.spyOn(api, 'query').mockReturnValue(request.promise);
      vi.spyOn(api, 'getMessages').mockResolvedValue([]);
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      const composer = screen.getByRole('textbox') as HTMLTextAreaElement;
      fireEvent.change(composer, { target: { value: 'First question' } });
      fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

      act(() => useStore.getState().draftMindMapQuestion(project.id, 'Explain attention.'));

      expect(composer.disabled).toBe(true);
      expect(query).toHaveBeenCalledTimes(1);
      await act(async () => {
        request.resolve({ answer: '', sources: [], chunks_used: 0, model_used: null, usage: {}, conversation_id: 'conversation-1' });
      });

      await waitFor(() => expect(composer.value).toBe('Explain attention.'));
      expect(composer.disabled).toBe(false);
      expect(useStore.getState().pendingMindMapQuestion).toBeNull();
      expect(query).toHaveBeenCalledTimes(1);
    });

    it('does not restore a submitted topic after a late failure across project changes', async () => {
      const request = deferred<Awaited<ReturnType<typeof api.query>>>();
      vi.spyOn(api, 'query').mockReturnValue(request.promise);
      vi.spyOn(api, 'getDocuments').mockResolvedValue([readyDocument]);
      vi.spyOn(api, 'getConversations').mockResolvedValue([]);
      vi.spyOn(console, 'error').mockImplementation(() => undefined);
      render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
      const composer = screen.getByRole('textbox') as HTMLTextAreaElement;
      act(() => useStore.getState().draftMindMapQuestion(project.id, 'Private topic'));
      await waitFor(() => expect(composer.value).toBe('Private topic'));
      fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

      await act(async () => {
        useStore.getState().selectProject({ ...project, id: 'project-2' });
        useStore.getState().selectProject(project);
        request.reject(new Error('Late failure'));
      });

      expect(composer.value).toBe('');
      expect(screen.queryByText('Private topic')).toBeNull();
    });
  });

  describe('source citations', () => {
    function renderAnswer(content: string, citations: Message['citations']) {
      useStore.setState({
        projects: [project],
        currentProject: project,
        documents: [readyDocument],
        currentConversation: conversation('conversation-1', project.id),
        messages: [{
          id: 'message-assistant',
          conversation_id: 'conversation-1',
          role: 'assistant',
          content,
          citations,
          created_at: '2026-08-23T00:00:00Z',
        }],
      });

      return render(<ChatArea onAddSourcesOpenChange={() => undefined} />);
    }

    it('matches sparse source numbers in the answer and hides uncited stored entries', () => {
      renderAnswer('The method [Source 1] improves the result [Source 5].', [
        { id: 1, source: 'Method paper', page: 2, text: 'The proposed method.' },
        { id: 2, source: 'Unused retrieval', page: 1, text: 'Unrelated context.' },
        { id: 5, source: 'Results paper', page: 8, text: 'The measured result.' },
      ]);

      expect(screen.getByRole('button', { name: 'Preview source 1' }).textContent).toBe('[1]');
      expect(screen.getByRole('button', { name: 'Preview source 5' }).textContent).toBe('[5]');
      expect(screen.queryByText('[2]')).toBeNull();
      expect(screen.queryByText('Unused retrieval')).toBeNull();
      expect(screen.getByText('Method paper')).toBeTruthy();
      expect(screen.getByText('Results paper')).toBeTruthy();
    });

    it('lets readers expand distinct excerpts from two chunks on the same page', () => {
      renderAnswer('Two findings support this conclusion [Source 1] [Source 5].', [
        { id: 1, chunk_id: 'chunk-a', source: 'Research paper', page: 3, text: 'First finding:  the method\nuses attention.' },
        { id: 5, chunk_id: 'chunk-b', source: 'Research paper', page: 3, text: 'Second finding:  the results\nimprove accuracy.' },
      ]);

      const firstExcerpt = screen.getByText('First finding: the method uses attention.');
      const secondExcerpt = screen.getByText('Second finding: the results improve accuracy.');
      const firstDisclosure = firstExcerpt.closest('details');
      const secondDisclosure = secondExcerpt.closest('details');
      expect(firstDisclosure).not.toBeNull();
      expect(secondDisclosure).not.toBeNull();
      expect(firstDisclosure).not.toBe(secondDisclosure);
      expect(firstDisclosure?.open).toBe(false);
      expect(secondDisclosure?.open).toBe(false);

      fireEvent.click(firstDisclosure!.querySelector('summary')!);

      expect(firstDisclosure?.open).toBe(true);
      expect(secondDisclosure?.open).toBe(false);
      expect(firstDisclosure?.textContent).toContain('[1]');
      expect(secondDisclosure?.textContent).toContain('[5]');
      expect(screen.getAllByText('Research paper')).toHaveLength(2);
    });

    it('keeps unnumbered legacy sources without inventing a citation mapping', () => {
      renderAnswer('The result is supported by [Source 5].', [
        { source: 'Older source', text: 'An older excerpt.' },
        { id: 'document-id', source: 'Legacy document', page: 2 },
        { id: 1, source: 'Unused numbered source' },
        { id: 5, source: 'Cited source' },
      ]);

      expect(screen.getByText('Older source')).toBeTruthy();
      expect(screen.getByText('Legacy document')).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Preview source 5' })).toBeTruthy();
      expect(screen.queryByText('Unused numbered source')).toBeNull();
      expect(screen.queryByText('[1]')).toBeNull();
      expect(screen.queryByText('[2]')).toBeNull();
      expect(screen.queryByText('[Source document-id]')).toBeNull();
    });

    it('retains sources in older answers without explicit source markers', () => {
      renderAnswer('This older answer uses an unnumbered citation style.', [
        { id: 5, source: 'Numbered source', page: 1 },
        { source: 'Unnumbered source', text: 'Preserved evidence.' },
      ]);

      expect(screen.getByText('Numbered source')).toBeTruthy();
      expect(screen.getByText('[5]')).toBeTruthy();
      expect(screen.getByText('Unnumbered source')).toBeTruthy();
      expect(screen.getByText('Preserved evidence.')).toBeTruthy();
    });

    it('matches compact references to the source list and opens the corresponding preview', () => {
      renderAnswer('The result [4].', [
        { id: 1, source: 'Unused source', text: 'Unused evidence.' },
        { id: 4, source: 'Results paper', page: 8, text: 'The measured result.' },
      ]);
      expect(screen.queryByText('Unused source')).toBeNull();
      fireEvent.mouseEnter(screen.getByRole('button', { name: 'Preview source 4' }));
      expect(screen.getByRole('tooltip').textContent).toContain('The measured result.');
      expect(screen.getByRole('tooltip').textContent).toContain('Page 8');
    });

    it.each([
      'Use `values[1]` to select the second element.',
      'See [1](https://example.com) for the linked example.',
    ])('preserves legacy sources when numbers occur only in code or links: %s', (content) => {
      renderAnswer(content, [{ id: 4, source: 'Legacy evidence', text: 'The original supporting excerpt.' }]);
      expect(screen.getByText('Legacy evidence')).toBeTruthy();
      expect(screen.queryByRole('button', { name: /Preview source/ })).toBeNull();
    });

    it('ignores even matching source numbers in code when deciding which passages were cited', () => {
      renderAnswer('Use `values[1]` or `values[4]`.', [
        { id: 1, source: 'First legacy source' },
        { id: 5, source: 'Second legacy source' },
      ]);
      expect(screen.getByText('First legacy source')).toBeTruthy();
      expect(screen.getByText('Second legacy source')).toBeTruthy();
    });
  });

  it('uses the shared brand mark decoratively in the empty welcome state', () => {
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [],
      currentConversation: null,
      messages: [],
    });

    const { container } = render(
      <ChatArea onAddSourcesOpenChange={() => undefined} />,
    );
    const welcome = container.querySelector('[data-layout="welcome-icon"]');
    const logo = welcome?.querySelector('[data-brand-logo="true"]');

    expect(logo).not.toBeNull();
    expect(logo?.getAttribute('aria-hidden')).toBe('true');
  });

  it('uses the shared brand mark decoratively for assistant messages', () => {
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation: conversation('conversation-1', project.id),
      messages: [{
        id: 'message-assistant',
        conversation_id: 'conversation-1',
        role: 'assistant',
        content: 'A concise answer.',
        citations: [],
        created_at: '2026-08-23T00:00:00Z',
      }],
    });

    const { container } = render(
      <ChatArea onAddSourcesOpenChange={() => undefined} />,
    );
    const logos = container.querySelectorAll('[data-brand-logo="true"]');

    expect(screen.getByText('A concise answer.')).toBeTruthy();
    expect(logos).toHaveLength(1);
    expect(logos[0].getAttribute('aria-hidden')).toBe('true');
  });

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
    render(
      <ChatArea onAddSourcesOpenChange={() => undefined} />,
    );

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

  it('keeps a refresh-only retry retryable when its same-conversation successor fails', async () => {
    const question = 'Can the retry survive a newer refresh?';
    const retryRefresh = deferred<Message[]>();
    const successorRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise)
      .mockReturnValueOnce(successorRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    const reselectingConversation = useStore.getState().selectConversation(currentConversation);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(3));

    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });

    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();

    successorRefresh.reject(new Error('The newer refresh failed'));
    await reselectingConversation;

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The conversation could not be refreshed.',
    );
    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh response' })).toBeTruthy();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('clears a refresh-only retry only after its same-conversation successor applies', async () => {
    const question = 'Can a newer refresh complete the retry?';
    const retryRefresh = deferred<Message[]>();
    const successorRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise)
      .mockReturnValueOnce(successorRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    const reselectingConversation = useStore.getState().selectConversation(currentConversation);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(3));

    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });

    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();

    await act(async () => {
      successorRefresh.resolve([
        {
          id: 'message-user',
          conversation_id: currentConversation.id,
          role: 'user',
          content: question,
          citations: [],
          created_at: '2026-08-23T00:00:00Z',
        },
        {
          id: 'message-assistant',
          conversation_id: currentConversation.id,
          role: 'assistant',
          content: 'The successor refresh completed.',
          citations: [],
          created_at: '2026-08-23T00:00:01Z',
        },
      ]);
      await reselectingConversation;
    });

    await waitFor(() => expect(screen.getByText('The successor refresh completed.')).toBeTruthy());
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('completes a refresh-only retry after a third reader applies while the second never settles', async () => {
    const question = 'Can a third refresh unblock this retry?';
    const retryRefresh = deferred<Message[]>();
    const secondRefresh = deferred<Message[]>();
    const thirdRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise)
      .mockReturnValueOnce(secondRefresh.promise)
      .mockReturnValueOnce(thirdRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    void useStore.getState().selectConversation(currentConversation);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(3));
    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });
    expect(screen.getByText(question)).toBeTruthy();

    const thirdRead = useStore.getState().fetchMessages(currentConversation.id);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(4));
    await act(async () => {
      thirdRefresh.resolve([
        {
          id: 'message-user',
          conversation_id: currentConversation.id,
          role: 'user',
          content: question,
          citations: [],
          created_at: '2026-08-23T00:00:00Z',
        },
        {
          id: 'message-assistant',
          conversation_id: currentConversation.id,
          role: 'assistant',
          content: 'The third reader completed the retry.',
          citations: [],
          created_at: '2026-08-23T00:00:01Z',
        },
      ]);
      await thirdRead;
    });

    await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false));
    expect(screen.getByText('The third reader completed the retry.')).toBeTruthy();
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('keeps refresh retry UI when a third reader fails while the second never settles', async () => {
    const question = 'Can a third failed refresh remain retryable?';
    const retryRefresh = deferred<Message[]>();
    const secondRefresh = deferred<Message[]>();
    const thirdRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise)
      .mockReturnValueOnce(secondRefresh.promise)
      .mockReturnValueOnce(thirdRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    void useStore.getState().selectConversation(currentConversation);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(3));
    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });
    expect(screen.getByText(question)).toBeTruthy();

    void useStore.getState().fetchMessages(currentConversation.id);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(4));
    thirdRefresh.reject(new Error('Third refresh failed'));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The conversation could not be refreshed.',
    );
    expect(screen.getByRole('button', { name: 'Refresh response' })).toBeTruthy();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false);
    expect(screen.getByText(question)).toBeTruthy();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('abandons a refresh-only retry benignly after its conversation changes', async () => {
    const question = 'Should an old retry stay quiet?';
    const retryRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const otherConversation = conversation('conversation-2', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise)
      .mockResolvedValueOnce([]);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    await useStore.getState().selectConversation(otherConversation);

    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });

    expect(useStore.getState().currentConversation).toEqual(otherConversation);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(question)).toBeNull();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('abandons a refresh-only retry benignly after account state clears', async () => {
    const question = 'Should logout surface an old refresh error?';
    const retryRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockRejectedValueOnce(new Error('Initial refresh failed'))
      .mockReturnValueOnce(retryRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('button', { name: 'Refresh response' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh response' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    act(() => {
      useStore.getState().clearAccountState();
    });

    await act(async () => {
      retryRefresh.resolve([]);
      await retryRefresh.promise;
    });

    expect(useStore.getState().currentProject).toBeNull();
    expect(screen.getByText('Create a project to get started')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('keeps a query pending through a same-conversation refresh superseder and offers retry when it fails', async () => {
    const question = 'What happens after the second refresh?';
    const queryRefresh = deferred<Message[]>();
    const newerRefresh = deferred<Message[]>();
    const currentConversation = conversation('conversation-1', project.id);
    const query = vi.spyOn(api, 'query').mockResolvedValue({
      answer: 'Answer',
      sources: [],
      chunks_used: 0,
      model_used: null,
      usage: {},
      conversation_id: currentConversation.id,
    });
    const getMessages = vi.spyOn(api, 'getMessages')
      .mockReturnValueOnce(queryRefresh.promise)
      .mockReturnValueOnce(newerRefresh.promise);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useStore.setState({
      projects: [project],
      currentProject: project,
      documents: [readyDocument],
      currentConversation,
      messages: [],
    });
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(1));
    const reselectingConversation = useStore.getState().selectConversation(currentConversation);
    await waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));

    await act(async () => {
      queryRefresh.resolve([]);
      await queryRefresh.promise;
    });

    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true);

    newerRefresh.reject(new Error('The newer read failed'));
    await reselectingConversation;

    expect((await screen.findByRole('alert')).textContent).toContain(
      'The question was sent, but the conversation could not be refreshed.',
    );
    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh response' })).toBeTruthy();
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
    const { container } = render(
      <ChatArea onAddSourcesOpenChange={() => undefined} />,
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'What does this source say?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));

    expect(screen.queryByText('Add a source to get started')).toBeNull();
    expect(screen.getByText('What does this source say?')).not.toBeNull();
    const streamingLogo = container.querySelector('[data-brand-logo="true"]');
    expect(streamingLogo).not.toBeNull();
    expect(streamingLogo?.getAttribute('aria-hidden')).toBe('true');

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
