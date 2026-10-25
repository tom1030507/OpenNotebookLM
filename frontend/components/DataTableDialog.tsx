'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clipboard, Download, Loader2, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import api from '@/lib/api';
import type { ProjectTable } from '@/lib/api';
import InlineCitation from './InlineCitation';

interface DataTableDialogProps {
  projectId: string;
  projectName: string;
  sourceIds?: string[];
  onClose: () => void;
}

const csvCell = (value: string) => {
  const safe = /^[\s]*[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
};

const markdownCell = (value: string) => value
  .replace(/\|/g, '\\|')
  .replace(/\r?\n/g, '<br>');

export default function DataTableDialog({
  projectId,
  projectName,
  sourceIds,
  onClose,
}: DataTableDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const requestRun = useRef(0);
  const currentProjectId = useRef(projectId);
  currentProjectId.current = projectId;
  const titleId = useId();
  const [instruction, setInstruction] = useState('');
  const [columnInput, setColumnInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  const [table, setTable] = useState<ProjectTable | null>(null);
  const [copyMessage, setCopyMessage] = useState('');
  const noSources = sourceIds?.length === 0;

  const close = () => {
    requestRun.current += 1;
    setIsGenerating(false);
    onClose();
  };

  useDialogFocus({ isOpen: true, onClose: close, dialogRef, initialFocusRef: closeRef });

  useEffect(() => () => { requestRun.current += 1; }, []);

  const invalidateTable = () => {
    requestRun.current += 1;
    setIsGenerating(false);
    setTable(null);
    setError('');
    setCopyMessage('');
  };

  const generate = async () => {
    const trimmedInstruction = instruction.trim();
    if (!trimmedInstruction || isGenerating || noSources) return;
    const run = requestRun.current + 1;
    requestRun.current = run;
    const isCurrent = () => requestRun.current === run
      && currentProjectId.current === projectId;
    setIsGenerating(true);
    setError('');
    setTable(null);
    setCopyMessage('');

    const columns = columnInput.split(',').map((column) => column.trim()).filter(Boolean);
    try {
      const result = await api.fetchProjectTable(projectId, {
        instruction: trimmedInstruction,
        ...(columns.length ? { columns } : {}),
        ...(sourceIds === undefined ? {} : { source_ids: sourceIds }),
      });
      if (isCurrent()) setTable(result);
    } catch {
      if (isCurrent()) setError('The table could not be generated. Please try again.');
    } finally {
      if (isCurrent()) setIsGenerating(false);
    }
  };

  const downloadCsv = () => {
    if (!table) return;
    const records = [table.columns, ...table.rows.map((row) => row.map((cell) => cell.value))];
    const content = `\uFEFF${records.map((row) => row.map(csvCell).join(',')).join('\r\n')}`;
    const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const filename = projectName
      .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, '_')
      .trim()
      .replace(/[. ]+$/g, '') || 'project';
    link.href = url;
    link.download = `${filename}-table.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const copyMarkdown = async () => {
    if (!table) return;
    const header = `| ${table.columns.map(markdownCell).join(' | ')} |`;
    const divider = `| ${table.columns.map(() => '---').join(' | ')} |`;
    const rows = table.rows.map((row) => (
      `| ${row.map((cell) => markdownCell(cell.value)).join(' | ')} |`
    ));
    try {
      await navigator.clipboard.writeText([header, divider, ...rows].join('\n'));
      setCopyMessage('Table copied as Markdown.');
    } catch {
      setCopyMessage('The table could not be copied.');
    }
  };

  const sourceById = new Map((table?.sources ?? []).map((source) => [source.id, source]));

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-2 sm:p-5">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isGenerating}
        className="flex h-[92dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl"
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3 sm:px-6">
          <h2 id={titleId} className="truncate text-base font-semibold">{projectName} data table</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={close}
            aria-label="Close data table dialog"
            className="rounded-lg p-2 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
          <p className="text-sm text-[var(--muted-foreground)]">
            Describe the rows you want. Each supported cell will show its source.
          </p>
          <label className="mt-4 block text-sm font-medium">
            Instruction
            <textarea
              aria-label="Instruction"
              value={instruction}
              maxLength={500}
              rows={3}
              onChange={(event) => {
                invalidateTable();
                setInstruction(event.target.value);
              }}
              placeholder="One row per paper: title, year, dataset, accuracy"
              className="mt-1 block w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-normal"
            />
          </label>
          <label className="mt-3 block text-sm font-medium">
            Columns (optional)
            <input
              aria-label="Columns (optional)"
              value={columnInput}
              onChange={(event) => {
                invalidateTable();
                setColumnInput(event.target.value);
              }}
              placeholder="Title, year, dataset, accuracy"
              className="mt-1 block w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-normal"
            />
          </label>
          {noSources && (
            <p className="mt-3 text-sm text-[var(--muted-foreground)]">
              Select at least one source to generate a table.
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={generate}
              disabled={isGenerating || noSources || !instruction.trim()}
              className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:brightness-95 focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Generate table
            </button>
            {isGenerating && (
              <span role="status" aria-label="Generating table" className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                Generating table…
              </span>
            )}
            {error && <p role="alert" className="text-sm text-[var(--error)]">{error}</p>}
          </div>

          {table && (
            <section aria-label="Generated data table" className="mt-6 border-t border-[var(--border)] pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">Generated table</h3>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={downloadCsv}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
                  >
                    <Download aria-hidden="true" className="h-4 w-4" />
                    Download CSV
                  </button>
                  <button
                    type="button"
                    onClick={copyMarkdown}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
                  >
                    <Clipboard aria-hidden="true" className="h-4 w-4" />
                    Copy as Markdown
                  </button>
                </div>
              </div>
              {copyMessage && <p role="status" className="mt-2 text-sm text-[var(--muted-foreground)]">{copyMessage}</p>}
              {table.rows.length === 0 ? (
                <p className="mt-4 text-sm text-[var(--muted-foreground)]">
                  No supported rows were found in the selected sources.
                </p>
              ) : (
                <div className="mt-4 overflow-x-auto rounded-lg border border-[var(--border)]">
                  <table aria-label="Extracted source table" className="min-w-full border-collapse text-left text-sm">
                    <thead className="bg-[var(--muted)]">
                      <tr>{table.columns.map((column, index) => (
                        <th key={`${column}-${index}`} scope="col" className="whitespace-nowrap border-b border-[var(--border)] px-3 py-2 font-semibold">{column}</th>
                      ))}</tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, rowIndex) => (
                        <tr key={rowIndex} className="border-b border-[var(--border)] last:border-b-0">
                          {row.map((cell, cellIndex) => {
                            const source = cell.source_id != null ? sourceById.get(cell.source_id) : undefined;
                            return (
                              <td key={cellIndex} className="min-w-32 px-3 py-2 align-top">
                                {cell.value}
                                {source && (
                                  <span className="ml-1">
                                    <InlineCitation
                                      id={source.id}
                                      citation={{ source: source.title, text: source.excerpt }}
                                    />
                                  </span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </div>,
    document.body,
  );
}
