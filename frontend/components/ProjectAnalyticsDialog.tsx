'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import api, {
  type Project,
  type ProjectAnalytics,
  type ProjectAnalyticsWindow,
} from '@/lib/api';
import useDialogFocus from '@/hooks/useDialogFocus';

interface ProjectAnalyticsDialogProps {
  project: Project;
  isOpen: boolean;
  onClose: () => void;
}

export default function ProjectAnalyticsDialog({
  project,
  isOpen,
  onClose,
}: ProjectAnalyticsDialogProps) {
  const [days, setDays] = useState<ProjectAnalyticsWindow>(7);
  const [analytics, setAnalytics] = useState<ProjectAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useDialogFocus({ isOpen, onClose, dialogRef, initialFocusRef: closeRef });

  useEffect(() => {
    if (!isOpen) return;

    let active = true;
    setLoading(true);
    setError('');
    api.getProjectAnalytics(project.id, days)
      .then((result) => {
        if (active) setAnalytics(result);
      })
      .catch(() => {
        if (active) setError('Failed to load project analytics.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [days, isOpen, project.id]);

  if (!isOpen) return null;

  const questionCount = analytics?.questions_by_day.reduce(
    (total, day) => total + day.question_count,
    0,
  ) ?? 0;
  const hasActivity = Boolean(
    questionCount
    || analytics?.conversation_count
    || analytics?.ratings.up
    || analytics?.ratings.down
    || analytics?.ratings.unrated,
  );
  const questions = analytics?.questions_by_day ?? [];
  const maximumQuestions = Math.max(1, ...questions.map((day) => day.question_count));
  const chartWidth = 720;
  const chartHeight = 140;
  const plotHeight = 108;
  const barStep = questions.length ? chartWidth / questions.length : chartWidth;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-3">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--popover)] shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] p-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">Project analytics</h2>
            <p className="text-sm text-[var(--muted-foreground)]">{project.name}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close analytics"
            className="rounded p-1 hover:bg-[var(--muted)]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto p-4">
          <label className="mb-4 flex items-center gap-2 text-sm">
            <span>Date range</span>
            <select
              aria-label="Date range"
              value={days}
              onChange={(event) => setDays(Number(event.target.value) as ProjectAnalyticsWindow)}
              className="h-9 rounded-md border border-[var(--input)] bg-[var(--card)] px-2"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </label>

          {loading && (
            <div className="flex items-center gap-2 py-8 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Loading analytics...</span>
            </div>
          )}
          {error && <p role="alert" className="py-4 text-sm text-[var(--error)]">{error}</p>}

          {!loading && !error && analytics && (
            <div className="space-y-6">
              {!hasActivity && (
                <p className="rounded-md bg-[var(--muted)] p-3 text-sm">
                  No activity in this period yet.
                </p>
              )}

              <dl className="grid grid-cols-2 gap-3">
                <div className="rounded-md bg-[var(--card)] p-3">
                  <dt className="text-xs text-[var(--muted-foreground)]">Questions</dt>
                  <dd className="mt-1 text-xl font-semibold">{questionCount}</dd>
                </div>
                <div className="rounded-md bg-[var(--card)] p-3">
                  <dt className="text-xs text-[var(--muted-foreground)]">Active conversations</dt>
                  <dd className="mt-1 text-xl font-semibold">{analytics.conversation_count}</dd>
                </div>
              </dl>

              <section aria-labelledby="analytics-questions-title">
                <h3 id="analytics-questions-title" className="mb-2 text-sm font-semibold">
                  Questions per day
                </h3>
                <svg
                  role="img"
                  aria-label="Questions per day"
                  viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                  className="h-36 w-full overflow-visible rounded-md bg-[var(--card)] p-2"
                >
                  <line x1="0" y1={plotHeight + 8} x2={chartWidth} y2={plotHeight + 8} stroke="currentColor" opacity="0.2" />
                  {questions.map((day, index) => {
                    const barHeight = day.question_count
                      ? Math.max(2, (day.question_count / maximumQuestions) * plotHeight)
                      : 0;
                    const x = index * barStep + Math.max(0, (barStep - 4) / 2);
                    return (
                      <rect
                        key={day.date}
                        x={x}
                        y={plotHeight + 8 - barHeight}
                        width={Math.max(1, barStep - 4)}
                        height={barHeight}
                        rx="2"
                        fill="var(--primary)"
                      >
                        <title>{`${day.date}: ${day.question_count} questions`}</title>
                      </rect>
                    );
                  })}
                  <text x="0" y={chartHeight - 4} fill="currentColor" fontSize="11">
                    {questions[0]?.date ?? ''}
                  </text>
                  <text x={chartWidth} y={chartHeight - 4} textAnchor="end" fill="currentColor" fontSize="11">
                    {questions[questions.length - 1]?.date ?? ''}
                  </text>
                </svg>
              </section>

              <section aria-labelledby="analytics-ratings-title">
                <h3 id="analytics-ratings-title" className="mb-2 text-sm font-semibold">Answer ratings</h3>
                <table aria-label="Answer ratings" className="w-full text-left text-sm">
                  <tbody>
                    {(['up', 'down', 'unrated'] as const).map((rating) => (
                      <tr key={rating} className="border-t border-[var(--border)]">
                        <th scope="row" className="py-2 font-medium capitalize">{rating}</th>
                        <td className="py-2 text-right">{analytics.ratings[rating]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              <section aria-labelledby="analytics-citations-title">
                <h3 id="analytics-citations-title" className="mb-2 text-sm font-semibold">
                  Top cited sources
                </h3>
                <table aria-label="Top cited sources" className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--muted-foreground)]">
                      <th scope="col" className="py-2 font-medium">Source</th>
                      <th scope="col" className="py-2 text-right font-medium">Citations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.top_cited_sources.length ? analytics.top_cited_sources.map((source) => (
                      <tr key={source.document_id} className="border-b border-[var(--border)]">
                        <td className="py-2">{source.title}</td>
                        <td className="py-2 text-right">{source.citation_count}</td>
                      </tr>
                    )) : (
                      <tr><td colSpan={2} className="py-2 text-[var(--muted-foreground)]">No cited sources.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>

              <section aria-labelledby="analytics-negative-title">
                <h3 id="analytics-negative-title" className="mb-2 text-sm font-semibold">
                  Recent down-rated questions
                </h3>
                <table aria-label="Recent down-rated questions" className="w-full text-left text-sm">
                  <tbody>
                    {analytics.recent_down_rated_questions.length ? analytics.recent_down_rated_questions.map((item, index) => (
                      <tr key={`${item.answered_at}-${index}`} className="border-t border-[var(--border)]">
                        <td className="py-2">{item.question}</td>
                        <td className="whitespace-nowrap py-2 pl-4 text-right text-[var(--muted-foreground)]">
                          {item.answered_at.slice(0, 10)}
                        </td>
                      </tr>
                    )) : (
                      <tr><td className="py-2 text-[var(--muted-foreground)]">No down-rated answers.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>

              <section aria-labelledby="analytics-uncited-title">
                <h3 id="analytics-uncited-title" className="mb-2 text-sm font-semibold">
                  Sources not cited in this period
                </h3>
                <table aria-label="Sources not cited in this period" className="w-full text-left text-sm">
                  <tbody>
                    {analytics.uncited_sources.length ? analytics.uncited_sources.map((source) => (
                      <tr key={source.document_id} className="border-t border-[var(--border)]">
                        <td className="py-2">{source.title}</td>
                      </tr>
                    )) : (
                      <tr><td className="py-2 text-[var(--muted-foreground)]">All current sources were cited.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
