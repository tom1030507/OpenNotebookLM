'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api from '@/lib/api';
import type { FlashcardsResponse, QuizResponse } from '@/lib/api';
import InlineCitation from './InlineCitation';

type StudyMode = 'flashcards' | 'quiz';
type Rating = 'got-it' | 'again';

interface StudyToolsDialogProps {
  projectId: string;
  mode: StudyMode;
  documentIds?: string[];
  onClose: () => void;
}

export default function StudyToolsDialog({
  projectId,
  mode,
  documentIds,
  onClose,
}: StudyToolsDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const requestId = useRef(0);
  const currentProjectId = useRef(projectId);
  currentProjectId.current = projectId;

  const [count, setCount] = useState(10);
  const [focus, setFocus] = useState('');
  const [flashcards, setFlashcards] = useState<FlashcardsResponse | null>(null);
  const [quiz, setQuiz] = useState<QuizResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [ratings, setRatings] = useState<Record<number, Rating>>({});
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  const close = () => {
    requestId.current += 1;
    setLoading(false);
    onClose();
  };

  useDialogFocus({
    isOpen: true,
    onClose: close,
    dialogRef,
    initialFocusRef: closeRef,
  });

  useEffect(() => {
    requestId.current += 1;
    setFlashcards(null);
    setQuiz(null);
    setLoading(false);
    setError('');
    setIndex(0);
    setFlipped(false);
    setRatings({});
    setAnswers({});
    setRevealed({});
    return () => { requestId.current += 1; };
  }, [projectId, mode]);

  const hasResult = mode === 'flashcards' ? flashcards !== null : quiz !== null;
  const cards = flashcards?.items ?? [];
  const questions = quiz?.items ?? [];
  const sources = mode === 'flashcards' ? flashcards?.sources ?? [] : quiz?.sources ?? [];
  const noReadySource = documentIds !== undefined && documentIds.length === 0;

  const generate = async () => {
    if (loading || noReadySource) return;
    const run = requestId.current + 1;
    requestId.current = run;
    const isCurrent = () => requestId.current === run
      && currentProjectId.current === projectId;
    const options = {
      ...(documentIds === undefined ? {} : { document_ids: documentIds }),
      count,
      ...(focus.trim() ? { focus: focus.trim() } : {}),
    };

    setLoading(true);
    setError('');
    setFlashcards(null);
    setQuiz(null);
    try {
      if (mode === 'flashcards') {
        const result = await api.fetchProjectFlashcards(projectId, options);
        if (isCurrent()) setFlashcards(result);
      } else {
        const result = await api.fetchProjectQuiz(projectId, options);
        if (isCurrent()) setQuiz(result);
      }
      if (isCurrent()) {
        setIndex(0);
        setFlipped(false);
        setRatings({});
        setAnswers({});
        setRevealed({});
      }
    } catch {
      if (isCurrent()) setError('Study material could not be generated. Please try again.');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  const changeOptions = () => {
    requestId.current += 1;
    setFlashcards(null);
    setQuiz(null);
    setError('');
  };

  const citation = (documentId: string) => {
    const sourceIndex = sources.findIndex((source) => source.document_id === documentId);
    const source = sources[sourceIndex];
    return source ? <InlineCitation
      id={sourceIndex + 1}
      citation={{ source: source.title, text: source.excerpt }}
    /> : null;
  };

  const title = mode === 'flashcards' ? 'Flashcards' : 'Practice quiz';
  const ratingsCount = (rating: Rating) => Object.values(ratings).filter((value) => value === rating).length;
  const correctCount = questions.filter((question, questionIndex) => (
    revealed[questionIndex] && answers[questionIndex] === question.answer_index
  )).length;
  const allQuestionsRevealed = questions.length > 0
    && questions.every((_, questionIndex) => revealed[questionIndex]);
  const selectedAnswer = answers[index];
  const questionRevealed = revealed[index] ?? false;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-[var(--border)] bg-[var(--popover)] shadow-xl"
      >
        <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] p-4">
          <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close study tools"
            onClick={close}
            className="rounded-lg p-2 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </header>

        <main className="min-h-0 overflow-y-auto p-4">
          {!hasResult && (
            <section className="space-y-4">
              <p className="text-sm text-[var(--muted-foreground)]">
                Generate source-based {mode === 'flashcards' ? 'cards' : 'questions'} for this project.
              </p>
              <label className="block text-sm font-medium" htmlFor="study-count">
                Number of {mode === 'flashcards' ? 'cards' : 'questions'}
                <input
                  id="study-count"
                  type="number"
                  min={5}
                  max={30}
                  step={1}
                  value={count}
                  onChange={(event) => setCount(Number(event.target.value))}
                  className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-normal"
                />
              </label>
              <label className="block text-sm font-medium" htmlFor="study-focus">
                Focus (optional)
                <input
                  id="study-focus"
                  type="text"
                  maxLength={500}
                  value={focus}
                  onChange={(event) => setFocus(event.target.value)}
                  placeholder="e.g. key terms or definitions"
                  className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-normal"
                />
              </label>
              {noReadySource && (
                <p role="status" className="text-sm text-[var(--muted-foreground)]">
                  Select at least one ready source in Studio to generate study material.
                </p>
              )}
              {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
              <button
                type="button"
                onClick={generate}
                disabled={loading || noReadySource || !Number.isInteger(count) || count < 5 || count > 30}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
              >
                {loading && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />}
                {error ? 'Retry' : loading ? 'Generating…' : `Generate ${mode === 'flashcards' ? 'flashcards' : 'quiz'}`}
              </button>
            </section>
          )}

          {hasResult && mode === 'flashcards' && cards.length === 0 && (
            <section role="status" className="space-y-4">
              <p>No study items were generated. Try again or select different sources.</p>
              <button type="button" onClick={generate} className="rounded-lg border border-[var(--border)] px-3 py-2">
                Retry
              </button>
              <button type="button" onClick={changeOptions} className="ml-2 rounded-lg px-3 py-2 hover:bg-[var(--muted)]">
                Change options
              </button>
            </section>
          )}

          {hasResult && mode === 'flashcards' && cards.length > 0 && (
            <section aria-label="Flashcard viewer" className="space-y-4">
              <p className="text-sm text-[var(--muted-foreground)]">Card {index + 1} of {cards.length}</p>
              <div className="flex min-h-40 flex-col justify-center rounded-lg border border-[var(--border)] bg-[var(--card)] p-6 text-center">
                <p className="text-lg font-medium">{flipped ? cards[index].back : cards[index].front}</p>
                <div className="mt-4">{citation(cards[index].document_id)}</div>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <button type="button" onClick={() => setFlipped(!flipped)} aria-pressed={flipped}
                  className="rounded-lg border border-[var(--border)] px-3 py-2">Flip card</button>
                {flipped && <>
                  <button type="button" aria-pressed={ratings[index] === 'got-it'}
                    onClick={() => setRatings({ ...ratings, [index]: 'got-it' })}
                    className="rounded-lg border border-[var(--border)] px-3 py-2">Got it</button>
                  <button type="button" aria-pressed={ratings[index] === 'again'}
                    onClick={() => setRatings({ ...ratings, [index]: 'again' })}
                    className="rounded-lg border border-[var(--border)] px-3 py-2">Again</button>
                </>}
              </div>
              <p className="text-center text-xs text-[var(--muted-foreground)]">
                Got it: {ratingsCount('got-it')} · Again: {ratingsCount('again')}
              </p>
              <div className="flex justify-between">
                <button type="button" disabled={index === 0} onClick={() => { setIndex(index - 1); setFlipped(false); }}
                  className="rounded-lg px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-40">Previous card</button>
                <button type="button" disabled={index >= cards.length - 1}
                  onClick={() => { setIndex(index + 1); setFlipped(false); }}
                  className="rounded-lg px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-40">Next card</button>
              </div>
            </section>
          )}

          {hasResult && mode === 'quiz' && questions.length === 0 && (
            <section role="status" className="space-y-4">
              <p>No study items were generated. Try again or select different sources.</p>
              <button type="button" onClick={generate} className="rounded-lg border border-[var(--border)] px-3 py-2">
                Retry
              </button>
              <button type="button" onClick={changeOptions} className="ml-2 rounded-lg px-3 py-2 hover:bg-[var(--muted)]">
                Change options
              </button>
            </section>
          )}

          {hasResult && mode === 'quiz' && questions.length > 0 && (
            <section aria-label="Quiz viewer" className="space-y-4">
              <p className="text-sm text-[var(--muted-foreground)]">Question {index + 1} of {questions.length}</p>
              <h3 className="text-lg font-medium">{questions[index].question}</h3>
              <fieldset className="space-y-2" disabled={questionRevealed}>
                <legend className="sr-only">Choose an answer</legend>
                {questions[index].options.map((option, optionIndex) => (
                  <label key={optionIndex} className="flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--border)] p-3">
                    <input
                      type="radio"
                      name={`study-answer-${index}`}
                      value={optionIndex}
                      checked={selectedAnswer === optionIndex}
                      onChange={() => setAnswers({ ...answers, [index]: optionIndex })}
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </fieldset>
              {!questionRevealed ? (
                <button type="button" disabled={selectedAnswer === undefined}
                  onClick={() => setRevealed({ ...revealed, [index]: true })}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 disabled:opacity-40">Check answer</button>
              ) : (
                <div role="status" aria-live="polite" className="space-y-2">
                  <p className="font-medium">
                    {selectedAnswer === questions[index].answer_index
                      ? 'Correct!'
                      : `Answer: ${questions[index].options[questions[index].answer_index]}`}
                  </p>
                  <p className="text-sm">{questions[index].explanation}</p>
                </div>
              )}
              <div>{citation(questions[index].document_id)}</div>
              <p className="text-center text-sm">
                {allQuestionsRevealed
                  ? `Final score: ${correctCount} / ${questions.length}`
                  : `Score: ${correctCount} / ${Object.keys(revealed).filter((key) => revealed[Number(key)]).length}`}
              </p>
              <div className="flex justify-between">
                <button type="button" disabled={index === 0} onClick={() => setIndex(index - 1)}
                  className="rounded-lg px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-40">Previous question</button>
                <button type="button" disabled={index >= questions.length - 1}
                  onClick={() => setIndex(index + 1)}
                  className="rounded-lg px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-40">Next question</button>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>,
    document.body,
  );
}
