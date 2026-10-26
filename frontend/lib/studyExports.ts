import type { FlashcardsResponse, QuizResponse } from './api';

type StudyExportResponse = FlashcardsResponse | QuizResponse;
type Delimiter = ',' | '\t';

/** Serialize delimited rows with RFC-style quoted fields and doubled quotes. */
export function serializeDelimitedRows(rows: string[][], delimiter: Delimiter): string {
  return rows.map((row) => row.map((value) => {
    if (value.includes(delimiter) || /["\r\n\t]/.test(value)) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  }).join(delimiter)).join('\r\n');
}

function sourceTitle(response: StudyExportResponse, documentId: string): string {
  return response.sources.find((source) => source.document_id === documentId)?.title ?? '';
}

function serializeCsvRows(rows: string[][]): string {
  const safeRows = rows.map((row, index) => (
    index === 0 ? row : row.map((value) => /^[\s]*[=+\-@＝＋－＠]/.test(value) ? `'${value}` : value)
  ));
  return `\uFEFF${serializeDelimitedRows(safeRows, ',')}`;
}

/** Export generated flashcards as a spreadsheet-friendly CSV. */
export function flashcardsToCsv(response: FlashcardsResponse): string {
  return serializeCsvRows([
    ['Front', 'Back', 'Source'],
    ...response.items.map((card) => [
      card.front,
      card.back,
      sourceTitle(response, card.document_id),
    ]),
  ]);
}

/** Export generated flashcards as an Anki-importable UTF-8 text file. */
export function flashcardsToAnkiTsv(response: FlashcardsResponse): string {
  const rows = serializeDelimitedRows(response.items.map((card) => [
    card.front,
    card.back,
    sourceTitle(response, card.document_id),
  ]), '\t');
  return [
    '#separator:Tab',
    '#columns:Front\tBack\tSource',
    rows,
  ].filter(Boolean).join('\r\n');
}

/** Export quiz questions, choices, answers, explanations, and sources as CSV. */
export function quizToCsv(response: QuizResponse): string {
  return serializeCsvRows([
    ['Question', 'Choice A', 'Choice B', 'Choice C', 'Choice D', 'Correct answer', 'Explanation', 'Source'],
    ...response.items.map((question) => [
      question.question,
      ...question.options,
      question.options[question.answer_index] ?? '',
      question.explanation,
      sourceTitle(response, question.document_id),
    ]),
  ]);
}

/** Export a quiz as Markdown with its answer key after all questions. */
export function quizToMarkdown(response: QuizResponse): string {
  const questionSections = response.items.flatMap((question, index) => {
    const source = sourceTitle(response, question.document_id);
    return [
      `## ${index + 1}. ${question.question}`,
      '',
      ...question.options.map((option, optionIndex) => (
        `- ${String.fromCharCode(65 + optionIndex)}. ${option}`
      )),
      ...(source ? ['', `Source: ${source}`] : []),
      '',
    ];
  });
  const answerKey = response.items.map((question, index) => {
    const letter = String.fromCharCode(65 + question.answer_index);
    const answer = question.options[question.answer_index] ?? '';
    return `${index + 1}. ${letter}. ${answer} — ${question.explanation}`;
  });

  return [
    '# Practice Quiz',
    '',
    ...questionSections,
    '## Answer key',
    '',
    ...answerKey,
  ].join('\r\n');
}

/** Download a UTF-8 text export in the browser. */
export function downloadStudyFile(
  filename: string,
  content: string,
  mimeType: string,
): void {
  const objectUrl = URL.createObjectURL(
    new Blob([content], { type: `${mimeType};charset=utf-8` }),
  );
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}
