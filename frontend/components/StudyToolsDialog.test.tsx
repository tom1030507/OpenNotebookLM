// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import api, { type FlashcardsResponse, type QuizResponse } from '@/lib/api';
import StudyToolsDialog from './StudyToolsDialog';

const source = {
  document_id: 'doc-1',
  title: 'Biology notes',
  excerpt: 'Cells contain a membrane and genetic material.',
};

const card = {
  front: 'What surrounds a cell?',
  back: 'A cell membrane.',
  document_id: source.document_id,
};

const flashcards = (items = [card]): FlashcardsResponse => ({
  project_id: 'project-1',
  project_name: 'Biology',
  generated_at: '2026-10-25T00:00:00Z',
  model_used: 'test-model',
  items,
  sources: items.length ? [source] : [],
});

const question = {
  question: 'Which structure surrounds a cell?',
  options: ['Nucleus', 'Membrane', 'Ribosome', 'Vacuole'] as [string, string, string, string],
  answer_index: 1,
  explanation: 'The source identifies the membrane as the cell boundary.',
  document_id: source.document_id,
};

const quiz = (items = [question]): QuizResponse => ({
  project_id: 'project-1',
  project_name: 'Biology',
  generated_at: '2026-10-25T00:00:00Z',
  model_used: 'test-model',
  items,
  sources: items.length ? [source] : [],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const generate = async (mode: 'flashcards' | 'quiz' = 'flashcards') => {
  fireEvent.click(screen.getByRole('button', {
    name: mode === 'flashcards' ? 'Generate flashcards' : 'Generate quiz',
  }));
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('StudyToolsDialog', () => {
  it('shows card front and flips to back', async () => {
    vi.spyOn(api, 'fetchProjectFlashcards').mockResolvedValue(flashcards());
    render(<StudyToolsDialog projectId="project-1" mode="flashcards" documentIds={['doc-1']} onClose={() => {}} />);

    await generate();

    expect(await screen.findByText(card.front)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Flip card' }));
    expect(screen.getByText(card.back)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Preview source 1' }));
    expect(await screen.findByText(source.excerpt)).toBeTruthy();
  });

  it('closes the citation preview before the study dialog on Escape', async () => {
    vi.spyOn(api, 'fetchProjectFlashcards').mockResolvedValue(flashcards());
    const onClose = vi.fn();
    render(<StudyToolsDialog
      projectId="project-1"
      mode="flashcards"
      documentIds={['doc-1']}
      onClose={onClose}
    />);

    await generate();
    await screen.findByText(card.front);
    fireEvent.click(screen.getByRole('button', { name: 'Flip card' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview source 1' }));
    expect(await screen.findByRole('tooltip')).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Flashcards' })).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('records got-it and again ratings while navigating', async () => {
    vi.spyOn(api, 'fetchProjectFlashcards').mockResolvedValue(flashcards([
      card,
      { ...card, front: 'What carries genes?' },
    ]));
    render(<StudyToolsDialog projectId="project-1" mode="flashcards" documentIds={['doc-1']} onClose={() => {}} />);

    await generate();
    await screen.findByText(card.front);
    fireEvent.click(screen.getByRole('button', { name: 'Flip card' }));
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next card' }));
    expect(screen.getByText('What carries genes?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Flip card' }));
    fireEvent.click(screen.getByRole('button', { name: 'Again' }));
    expect(screen.getByText('Got it: 1 · Again: 1')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Previous card' }));
    expect(screen.getByText(card.front)).toBeTruthy();
  });

  it('reveals the quiz answer and scores completed quiz', async () => {
    vi.spyOn(api, 'fetchProjectQuiz').mockResolvedValue(quiz());
    render(<StudyToolsDialog projectId="project-1" mode="quiz" documentIds={['doc-1']} onClose={() => {}} />);

    await generate('quiz');
    expect(await screen.findByText(question.question)).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: 'Membrane' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));

    expect(screen.getByText(question.explanation)).toBeTruthy();
    expect(screen.getByText('Final score: 1 / 1')).toBeTruthy();
  });

  it('shows source excerpt, empty, and retryable error states', async () => {
    const request = vi.spyOn(api, 'fetchProjectFlashcards')
      .mockResolvedValueOnce(flashcards([]))
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce(flashcards());
    render(<StudyToolsDialog projectId="project-1" mode="flashcards" documentIds={['doc-1']} onClose={() => {}} />);

    await generate();
    expect(await screen.findByText(/no study items were generated/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/could not be generated/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(card.front)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(3);
  });

  it('explains when no ready source is selected and skips the request', () => {
    const request = vi.spyOn(api, 'fetchProjectFlashcards');
    render(<StudyToolsDialog projectId="project-1" mode="flashcards" documentIds={[]} onClose={() => {}} />);

    expect(screen.getByText(/select at least one ready source/i)).toBeTruthy();
    expect(request).not.toHaveBeenCalled();
  });

  it('ignores late responses after close or a project change', async () => {
    const first = deferred<FlashcardsResponse>();
    const second = deferred<FlashcardsResponse>();
    const third = deferred<FlashcardsResponse>();
    vi.spyOn(api, 'fetchProjectFlashcards')
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise);
    const onClose = vi.fn();
    const view = render(
      <StudyToolsDialog projectId="project-1" mode="flashcards" documentIds={['doc-1']} onClose={onClose} />,
    );

    await generate();
    view.rerender(
      <StudyToolsDialog projectId="project-2" mode="flashcards" documentIds={['doc-2']} onClose={onClose} />,
    );
    await generate();
    await act(async () => {
      first.resolve(flashcards([{ ...card, front: 'Stale project card' }]));
      await first.promise;
    });
    expect(screen.queryByText('Stale project card')).toBeNull();
    await act(async () => {
      second.resolve(flashcards([{ ...card, front: 'Current project card' }]));
      await second.promise;
    });
    expect(screen.getByText('Current project card')).toBeTruthy();

    view.rerender(
      <StudyToolsDialog projectId="project-3" mode="flashcards" documentIds={['doc-3']} onClose={onClose} />,
    );
    await generate();
    fireEvent.click(screen.getByRole('button', { name: 'Close study tools' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await act(async () => {
      third.resolve(flashcards([{ ...card, front: 'Late closed card' }]));
      await third.promise;
    });
    expect(screen.queryByText('Late closed card')).toBeNull();
  });
});
