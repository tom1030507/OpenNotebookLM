import type { Element, ElementContent, Root } from 'hast';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import type { Citation } from './api';

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

export function rehypeCitations({ ids }: { ids: Set<number> }) {
  return (tree: Root) => {
    transformCitations(tree, ids);
  };
}

// The source list and inline controls must share this walk: scanning raw
// Markdown would mistake array indexes or link labels for supporting evidence.
function transformCitations(tree: Root, ids: Set<number>): Set<number> {
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
          children: [{ type: 'text', value: `[${id}]` }],
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
