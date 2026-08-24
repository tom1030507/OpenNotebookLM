// @vitest-environment jsdom

import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-syntax-highlighter', async () => {
  const { createElement } = await import('react');

  return {
    Prism: ({
      children,
      PreTag = 'pre',
    }: {
      children: unknown;
      PreTag?: 'pre' | 'div';
    }) => createElement(PreTag, null, createElement('code', null, children)),
  };
});

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  vscDarkPlus: {},
}));

import MarkdownRenderer from './MarkdownRenderer';

describe('MarkdownRenderer highlighter', () => {
  it('replaces the language fallback with the highlighter\'s non-pre container', async () => {
    const { container } = render(
      <MarkdownRenderer content={'```ts\nconst answer = 42;\n```'} />,
    );

    await waitFor(() => expect(container.querySelectorAll('pre')).toHaveLength(0));
    const code = container.querySelector('code');
    expect(code?.textContent).toContain('const answer = 42;');
    expect(code?.parentElement?.tagName).toBe('DIV');
  });
});
