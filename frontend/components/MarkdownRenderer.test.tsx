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

  it('renders dollar and TeX inline and display math', () => {
    const { container } = render(
      <MarkdownRenderer
        content={'$x^2$\n\n$$\n\\frac{1}{2}\n$$\n\n\\(a+b\\)\n\n\\[c=d\\]'}
      />,
    );

    expect(container.querySelectorAll('.katex')).toHaveLength(4);
    expect(container.querySelectorAll('.katex-display')).toHaveLength(2);
  });

  it('keeps citations next to math as citation controls', () => {
    const { container } = render(
      <MarkdownRenderer
        content={'For \\(x^2\\), see [Source 1].'}
        citations={[{ id: 1, source: 'Math paper.pdf', text: 'A cited equation.' }]}
      />,
    );
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.querySelector('button[aria-label="Preview source 1"]')).not.toBeNull();
  });

  it('keeps currency dollars literal and renders a later inline formula', () => {
    const { container } = render(
      <MarkdownRenderer content="The $5 plan includes $x^2$. An unmatched price is $10." />,
    );

    expect(container.querySelector('p')?.textContent).toContain('The $5 plan includes ');
    expect(container.querySelector('p')?.textContent).toContain('An unmatched price is $10.');
    expect(container.querySelectorAll('.katex')).toHaveLength(1);
  });
});
