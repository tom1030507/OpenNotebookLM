// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  downloadStudyFile,
  flashcardsToAnkiTsv,
  flashcardsToCsv,
  quizToCsv,
  quizToMarkdown,
  serializeDelimitedRows,
} from './studyExports';
import type { FlashcardsResponse, QuizResponse } from './api';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const flashcards: FlashcardsResponse = {
  project_id: 'project-1',
  project_name: 'Biology',
  generated_at: '2026-10-26T00:00:00Z',
  model_used: 'test-model',
  selected_ready_source_count: 1,
  sources_considered: 1,
  items: [{
    front: '細胞	由什麼組成？',
    back: '膜, 細胞質\n"細胞核"',
    document_id: 'doc-1',
  }],
  sources: [{
    document_id: 'doc-1',
    title: '細胞, 筆記',
    excerpt: 'Source excerpt',
  }],
};

const quiz: QuizResponse = {
  project_id: 'project-1',
  project_name: 'Biology',
  generated_at: '2026-10-26T00:00:00Z',
  model_used: 'test-model',
  selected_ready_source_count: 1,
  sources_considered: 1,
  items: [{
    question: '細胞, 外層是什麼？',
    options: ['細胞核', '細胞膜', '核糖體', '液泡'],
    answer_index: 1,
    explanation: '來源寫著 "細胞膜"。',
    document_id: 'doc-1',
  }],
  sources: [{
    document_id: 'doc-1',
    title: '細胞筆記',
    excerpt: 'Source excerpt',
  }],
};

describe('study export formats', () => {
  it('quotes CSV commas, quotes, and newlines', () => {
    expect(serializeDelimitedRows(
      [['front, with comma', 'say "hello"', 'line one\nline two']],
      ',',
    )).toBe('"front, with comma","say ""hello""","line one\nline two"');
  });

  it('quotes TSV tabs, quotes, and newlines', () => {
    expect(serializeDelimitedRows(
      [['front\tback', 'say "hello"', 'line one\r\nline two']],
      '\t',
    )).toBe('"front\tback"\t"say ""hello"""\t"line one\r\nline two"');
  });

  it('exports flashcards as CSV with source titles and CJK text', () => {
    expect(flashcardsToCsv(flashcards)).toBe(
      '\uFEFFFront,Back,Source\r\n'
      + '"細胞\t由什麼組成？","膜, 細胞質\n""細胞核""","細胞, 筆記"',
    );
  });

  it('keeps formula-leading CSV fields as text', () => {
    const response: FlashcardsResponse = {
      ...flashcards,
      items: [{ ...flashcards.items[0], front: '=SUM(1,1)', back: '＝SUM(1,1)' }],
    };

    expect(flashcardsToCsv(response)).toBe(
      '\uFEFFFront,Back,Source\r\n'
      + "\"'=SUM(1,1)\",\"'＝SUM(1,1)\",\"細胞, 筆記\"",
    );
  });

  it('exports flashcards as an Anki TSV with separate front and back fields', () => {
    expect(flashcardsToAnkiTsv(flashcards)).toBe(
      '#separator:Tab\r\n'
      + '#columns:Front\tBack\tSource\r\n'
      + '"細胞\t由什麼組成？"\t"膜, 細胞質\n""細胞核"""\t細胞, 筆記',
    );
  });

  it('exports quiz questions and choices to CSV with the correct answer and source', () => {
    expect(quizToCsv(quiz)).toBe(
      '\uFEFFQuestion,Choice A,Choice B,Choice C,Choice D,Correct answer,Explanation,Source\r\n'
      + '"細胞, 外層是什麼？",細胞核,細胞膜,核糖體,液泡,細胞膜,'
      + '"來源寫著 ""細胞膜""。",細胞筆記',
    );
  });

  it('puts quiz answers in a separate Markdown answer key', () => {
    expect(quizToMarkdown(quiz)).toBe(
      '# Practice Quiz\r\n\r\n'
      + '## 1. 細胞, 外層是什麼？\r\n\r\n'
      + '- A. 細胞核\r\n- B. 細胞膜\r\n- C. 核糖體\r\n- D. 液泡\r\n\r\n'
      + 'Source: 細胞筆記\r\n\r\n'
      + '## Answer key\r\n\r\n'
      + '1. B. 細胞膜 — 來源寫著 "細胞膜"。',
    );
  });

  it('downloads the export using a text blob and the requested filename', () => {
    const createObjectURL = vi.fn(() => 'blob:study-export');
    const revokeObjectURL = vi.fn();
    const downloads: Array<{ href: string; filename: string }> = [];
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) {
      downloads.push({ href: this.href, filename: this.download });
    });

    downloadStudyFile('flashcards.csv', 'Front,Back', 'text/csv');

    expect(createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ type: 'text/csv;charset=utf-8' }));
    expect(downloads).toEqual([{ href: 'blob:study-export', filename: 'flashcards.csv' }]);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:study-export');
  });
});
