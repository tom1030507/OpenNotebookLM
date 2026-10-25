import type { Element, ElementContent, Root } from 'hast';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import type { Citation, CitationCheck } from './api';

const CITATION_LABEL = /\[(?:Source\s+)?(\d+)\]/gi;
const parser = unified().use(remarkParse).use(remarkGfm).use(remarkRehype);

export function citationId(citation: Citation): number | null {
  return typeof citation.id === 'number' && Number.isSafeInteger(citation.id) && citation.id > 0
    ? citation.id
    : null;
}

export function referencedCitationIds(content: string, citations: Citation[]): Set<number> {
  const ids = new Set(citations.map(citationId).filter((id): id is number => id !== null));
  const tree = parser.runSync(parser.parse(content)) as Root;
  return transformCitations(tree, ids);
}

// shortcut: reads the generated note Markdown layouts, add a citation field if that format changes.
export function savedAnswerCitations(content: string): Citation[] {
  const sourceStart = content.lastIndexOf('\n\n**Sources**\n');
  if (sourceStart < 0) return [];

  const citations: Citation[] = [];
  let source = '';
  let sourceId = '';
  let current: Citation | null = null;
  const lines = content.slice(sourceStart).split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const legacy = line.match(/^- \[(\d+)\] (.+)$/);
    if (legacy) {
      const pageStart = legacy[2].lastIndexOf(', page ');
      const title = pageStart < 0 ? legacy[2] : legacy[2].slice(0, pageStart);
      const page = pageStart < 0 ? undefined : Number(legacy[2].slice(pageStart + 7));
      current = {
        id: Number(legacy[1]),
        source: title,
        document_id: title,
        ...(page !== undefined && Number.isFinite(page) ? { page } : {}),
      };
      citations.push(current);
      continue;
    }

    const group = line.match(/^- (.+)$/);
    if (group) {
      const hasPassages = /^  - /.test(lines[index + 1] ?? '');
      const detail = group[1];
      const pageStart = hasPassages ? -1 : detail.lastIndexOf(', page ');
      source = pageStart < 0 ? detail : detail.slice(0, pageStart);
      sourceId = hasPassages ? `${index}:${source}` : source;
      const page = pageStart < 0 ? undefined : Number(detail.slice(pageStart + 7));
      current = hasPassages ? null : {
        source,
        document_id: sourceId,
        ...(page !== undefined && Number.isFinite(page) ? { page } : {}),
      };
      if (current) {
        citations.push(current);
      }
      continue;
    }

    const passage = line.match(/^  - (.*)$/);
    if (passage) {
      const id = passage[1].match(/^\[(\d+)\]/)?.[1];
      const page = passage[1].match(/, page (.+)$/)?.[1];
      current = {
        source,
        document_id: sourceId || source,
        ...(id ? { id: Number(id) } : {}),
        ...(page && Number.isFinite(Number(page)) ? { page: Number(page) } : {}),
      };
      citations.push(current);
      continue;
    }

    const excerpt = line.match(/^ {2,4}> (.*)$/);
    if (excerpt) {
      if (!current && source) {
        current = {
          source,
          document_id: sourceId || source,
        };
        citations.push(current);
      }
      if (current) current.text = excerpt[1];
    }
  }
  return citations;
}

export function rehypeCitations({
  ids,
  citationLabels,
  citationChecks,
}: {
  ids: Set<number>;
  citationLabels?: Map<number, number>;
  citationChecks?: CitationCheck[];
}) {
  return (tree: Root) => {
    transformCitations(tree, ids, citationLabels);
    transformCitationChecks(tree, citationChecks ?? []);
  };
}

function transformCitationChecks(tree: Root, checks: CitationCheck[]): void {
  const unsupported = new Set(
    checks.filter((check) => !check.supported).map((check) => check.sentence_index),
  );
  if (unsupported.size === 0) return;

  let sentenceIndex = 0;
  let sentenceHasText = false;
  const boundary = /(?<!\d)[.!?。！？]+(?:\s*\[Source\s+\d+\])*|\n+/g;
  const wrap = (child: ElementContent): Element => ({
    type: 'element',
    tagName: 'span',
    properties: {
      className: ['border-b', 'border-dotted', 'border-[var(--muted-foreground)]'],
      title: 'The cited passage may not support this.',
      'data-citation-support': 'unsupported',
    },
    children: [child],
  });

  const visit = (parent: Root | Element) => {
    for (let index = 0; index < parent.children.length; index += 1) {
      const child = parent.children[index];
      if (child.type === 'text') {
        const replacement: ElementContent[] = [];
        let offset = 0;
        for (const match of child.value.matchAll(boundary)) {
          const end = match.index! + match[0].length;
          const value = child.value.slice(offset, end);
          if (value) {
            const text: ElementContent = { type: 'text', value };
            replacement.push(unsupported.has(sentenceIndex) && value.trim() ? wrap(text) : text);
            sentenceHasText ||= Boolean(value.trim());
          }
          if (sentenceHasText) sentenceIndex += 1;
          sentenceHasText = false;
          offset = end;
        }
        const tail = child.value.slice(offset);
        if (tail) {
          const text: ElementContent = { type: 'text', value: tail };
          replacement.push(unsupported.has(sentenceIndex) && tail.trim() ? wrap(text) : text);
          sentenceHasText ||= Boolean(tail.trim());
        }
        if (replacement.length > 0) {
          parent.children.splice(index, 1, ...replacement);
          index += replacement.length - 1;
        }
        continue;
      }
      if (child.type !== 'element') continue;

      if (child.tagName === 'br') {
        if (sentenceHasText) sentenceIndex += 1;
        sentenceHasText = false;
        continue;
      }

      if (child.tagName === 'a' && child.properties['data-citation-id'] !== undefined) {
        sentenceHasText = true;
        if (unsupported.has(sentenceIndex)) {
          parent.children[index] = wrap(child);
        }
        continue;
      }

      visit(child);
      if (/^(p|h[1-6]|li|td|th|pre)$/.test(child.tagName)) {
        if (sentenceHasText) sentenceIndex += 1;
        sentenceHasText = false;
      }
    }
  };

  visit(tree);
}

// The source list and inline controls must share this walk: scanning raw
// Markdown would mistake array indexes or link labels for supporting evidence.
function transformCitations(
  tree: Root,
  ids: Set<number>,
  citationLabels?: Map<number, number>,
): Set<number> {
  const referenced = new Set<number>();
  const visit = (parent: Root | Element) => {
    for (let index = 0; index < parent.children.length; index += 1) {
      const child = parent.children[index];
      if (child.type === 'element') {
        // Markdown links and code must keep their literal content. Processing
        // the parsed tree also avoids breaking tables, emphasis or link URLs.
        if (!['a', 'code', 'pre'].includes(child.tagName)) visit(child);
        continue;
      }
      if (child.type !== 'text') continue;

      const replacement: ElementContent[] = [];
      let offset = 0;
      for (const match of child.value.matchAll(CITATION_LABEL)) {
        const id = Number(match[1]);
        if (!ids.has(id)) continue;
        referenced.add(id);
        const start = match.index!;
        if (start > offset) replacement.push({ type: 'text', value: child.value.slice(offset, start) });
        replacement.push({
          type: 'element',
          tagName: 'a',
          properties: { href: `#citation-${id}`, 'data-citation-id': id },
          children: [{ type: 'text', value: `[${citationLabels?.get(id) ?? id}]` }],
        });
        offset = start + match[0].length;
      }
      if (replacement.length === 0) continue;
      if (offset < child.value.length) replacement.push({ type: 'text', value: child.value.slice(offset) });
      parent.children.splice(index, 1, ...replacement);
      index += replacement.length - 1;
    }
  };
  visit(tree);
  return referenced;
}
