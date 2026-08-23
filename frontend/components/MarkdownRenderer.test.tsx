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
});
