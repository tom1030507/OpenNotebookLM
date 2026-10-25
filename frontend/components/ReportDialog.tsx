'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { BookmarkPlus, Check, Download, Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api from '@/lib/api';
import type { ProjectReport, ReportFormat } from '@/lib/api';
import MarkdownRenderer from './MarkdownRenderer';

const FORMATS: { value: ReportFormat; title: string; description: string }[] = [
  { value: 'briefing', title: 'Briefing', description: 'A concise executive summary of the main findings and caveats.' },
  { value: 'study_guide', title: 'Study guide', description: 'Key concepts, definitions, explanations, and review questions.' },
  { value: 'faq', title: 'FAQ', description: 'Common questions with answers grounded in your sources.' },
  { value: 'timeline', title: 'Timeline', description: 'Dated events and milestones in chronological order.' },
  { value: 'custom', title: 'Custom', description: 'Describe the structure or focus you want for this report.' },
];

interface ReportDialogProps {
  projectId: string;
  projectName: string;
  documentIds?: string[];
  onClose: () => void;
  onSave?: (markdown: string) => Promise<void>;
}

export default function ReportDialog({
  projectId,
  projectName,
  documentIds,
  onClose,
  onSave,
}: ReportDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const requestRun = useRef(0);
  const titleId = useId();
  const [format, setFormat] = useState<ReportFormat>('briefing');
  const [instruction, setInstruction] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  const [report, setReport] = useState<ProjectReport | null>(null);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const selectedFormat = FORMATS.find((item) => item.value === format) ?? FORMATS[0];
  const noSources = documentIds?.length === 0;

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  useEffect(() => () => { requestRun.current += 1; }, []);

  const generate = async () => {
    const run = requestRun.current + 1;
    requestRun.current = run;
    setIsGenerating(true);
    setError('');
    setReport(null);
    setSaveState('idle');
    try {
      const result = await api.fetchProjectReport(projectId, {
        format,
        ...(format === 'custom' ? { instruction: instruction.trim() } : {}),
        ...(documentIds === undefined ? {} : { document_ids: documentIds }),
      });
      if (requestRun.current === run) setReport(result);
    } catch {
      if (requestRun.current === run) setError('The report could not be generated. Please try again.');
    } finally {
      if (requestRun.current === run) setIsGenerating(false);
    }
  };

  const download = () => {
    if (!report) return;
    const blob = new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const filename = projectName
      .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, '_')
      .trim()
      .replace(/[. ]+$/g, '') || 'report';
    link.href = url;
    link.download = `${filename}-report.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const save = async () => {
    if (!onSave || !report) return;
    setSaveState('saving');
    try {
      await onSave(report.markdown);
      setSaveState('saved');
    } catch {
      setSaveState('error');
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-2 sm:p-5">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isGenerating}
        className="flex h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl"
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3 sm:px-6">
          <h2 id={titleId} className="truncate text-base font-semibold">{projectName} report</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close report dialog"
            className="rounded-lg p-2 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-medium">
              Report format
              <select
                aria-label="Report format"
                value={format}
                onChange={(event) => setFormat(event.target.value as ReportFormat)}
                className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
              >
                {FORMATS.map((item) => (
                  <option key={item.value} value={item.value}>{item.title}</option>
                ))}
              </select>
            </label>
            <p className="min-h-10 flex-1 basis-full text-sm text-[var(--muted-foreground)] sm:basis-0">
              {selectedFormat.description}
            </p>
          </div>

          {format === 'custom' && (
            <label className="mt-4 flex flex-col gap-1 text-sm font-medium">
              Custom instructions
              <textarea
                aria-label="Custom instructions"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                maxLength={500}
                rows={3}
                placeholder="Describe the report you want"
                className="resize-y rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-normal"
              />
              <span className="text-xs font-normal text-[var(--muted-foreground)]">
                {instruction.length}/500 characters
              </span>
            </label>
          )}

          {noSources && (
            <p className="mt-4 text-sm text-[var(--muted-foreground)]">
              Select at least one source to generate a report.
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={generate}
              disabled={isGenerating || noSources || (format === 'custom' && !instruction.trim())}
              className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:brightness-95 focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Generate report
            </button>
            {isGenerating && (
              <span role="status" aria-label="Generating report" className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                Generating report…
              </span>
            )}
          </div>
          {error && <p role="alert" className="mt-3 text-sm text-[var(--error)]">{error}</p>}

          {report && (
            <section aria-label="Generated report" className="mt-6 border-t border-[var(--border)] pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">Generated report</h3>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={download}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
                  >
                    <Download aria-hidden="true" className="h-4 w-4" />
                    Download Markdown
                  </button>
                  {onSave && (
                    <button
                      type="button"
                      onClick={save}
                      disabled={saveState === 'saving' || saveState === 'saved'}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-50"
                    >
                      {saveState === 'saving' ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        : saveState === 'saved' ? <Check aria-hidden="true" className="h-4 w-4" />
                          : <BookmarkPlus aria-hidden="true" className="h-4 w-4" />}
                      {saveState === 'saving' ? 'Saving…'
                        : saveState === 'saved' ? 'Saved to notes' : 'Save report to notes'}
                    </button>
                  )}
                </div>
              </div>
              {saveState === 'error' && (
                <p role="alert" className="mt-2 text-sm text-[var(--error)]">
                  Could not save to notes. Please try again.
                </p>
              )}
              <div className="mt-4">
                <MarkdownRenderer content={report.markdown} citations={report.citations} className="text-sm" />
              </div>
            </section>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
