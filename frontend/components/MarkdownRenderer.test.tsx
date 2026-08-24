// @vitest-environment jsdom

import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const syntaxHighlighterModule = vi.hoisted(() => {
  const promise = new Promise<unknown>(() => undefined);
  return { promise };
});

vi.mock('react-syntax-highlighter', () => syntaxHighlighterModule.promise);

import MarkdownRenderer from './MarkdownRenderer';

describe('MarkdownRenderer', () => {
  it('owns a fenced-code fallback with exactly one pre and a direct code child', () => {
    const { container } = render(
      <MarkdownRenderer content={'```ts\nconst answer = 42;\n```'} />,
    );

    const pre = container.querySelector('pre');
    expect(container.querySelectorAll('pre')).toHaveLength(1);
    expect(pre?.querySelector(':scope > code')?.textContent).toBe('const answer = 42;');
  });

  it('keeps an unlabelled fence and inline code in their separate valid structures', () => {
    const { container } = render(
      <MarkdownRenderer content={'Use `inline value` here.\n\n```\nplain fallback\n```'} />,
    );

    const inlineCode = container.querySelector('p > code');
    const fencedCode = container.querySelector('pre > code');
    expect(inlineCode?.textContent).toBe('inline value');
    expect(inlineCode?.parentElement?.tagName).toBe('P');
    expect(container.querySelectorAll('pre')).toHaveLength(1);
    expect(fencedCode?.textContent).toBe('plain fallback\n');
  });
});
