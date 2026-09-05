// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MarkdownRenderer from './MarkdownRenderer';

const citations = [
  { id: 1, source: 'Attention paper.pdf', page: 1, text: 'The architecture uses attention.' },
  { id: 4, source: 'Attention paper.pdf', page: 1, text: 'The results allow parallel training.' },
];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('inline citation previews', () => {
  it('renders adjacent sparse references as compact buttons tied to their own excerpts', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MarkdownRenderer content="Attention helps [Source 1][Source 4]." citations={citations} />,
    );
    const first = screen.getByRole('button', { name: 'Preview source 1' });
    const fourth = screen.getByRole('button', { name: 'Preview source 4' });
    expect(first.textContent).toBe('[1]');
    expect(fourth.textContent).toBe('[4]');
    expect(container.textContent).toBe('Attention helps [1][4].');
    expect(screen.queryByRole('tooltip')).toBeNull();

    await user.hover(fourth);
    const preview = screen.getByRole('tooltip');
    expect(preview.textContent).toContain('Attention paper.pdf');
    expect(preview.textContent).toContain('Page 1');
    expect(preview.textContent).toContain(citations[1].text);
    expect(preview.textContent).not.toContain(citations[0].text);
    expect(fourth.getAttribute('aria-describedby')).toBe(preview.id);
    expect(container.contains(preview)).toBe(false);
  });

  it('supports keyboard focus and Escape without leaving a preview open', async () => {
    const user = userEvent.setup();
    render(<MarkdownRenderer content="Result [Source 4]." citations={citations} />);
    await user.tab();
    expect(screen.getByRole('tooltip').textContent).toContain(citations[1].text);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Preview source 4' }));
  });

  it('opens by touch-style click and dismisses when the reader clicks elsewhere', () => {
    render(<MarkdownRenderer content="Result [4]." citations={citations} />);
    fireEvent.click(screen.getByRole('button', { name: 'Preview source 4' }));
    expect(screen.getByRole('tooltip').textContent).toContain(citations[1].text);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('keeps the preview open while the pointer moves onto the preview text', () => {
    vi.useFakeTimers();
    render(<MarkdownRenderer content="Result [Source 4]." citations={citations} />);
    const trigger = screen.getByRole('button', { name: 'Preview source 4' });
    fireEvent.mouseEnter(trigger);
    const preview = screen.getByRole('tooltip');
    fireEvent.mouseLeave(trigger);
    fireEvent.mouseEnter(preview);
    act(() => vi.advanceTimersByTime(300));
    expect(screen.getByRole('tooltip')).toBe(preview);
    fireEvent.mouseLeave(preview);
    act(() => vi.advanceTimersByTime(300));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('renders references inside formatted prose while leaving code and ordinary links intact', () => {
    const { container } = render(<MarkdownRenderer
      content={'**Finding [Source 1]**\n\n- Result [4]\n\n`[Source 1]`\n\n```\n[Source 4]\n```\n\n[Source 1](https://example.com)'}
      citations={citations}
    />);
    expect(screen.getAllByRole('button', { name: /Preview source/ })).toHaveLength(2);
    expect(container.querySelector('strong button')?.textContent).toBe('[1]');
    expect(container.querySelector('li button')?.textContent).toBe('[4]');
    expect(container.querySelector('p > code')?.textContent).toBe('[Source 1]');
    expect(container.querySelector('pre > code')?.textContent).toContain('[Source 4]');
    const link = screen.getByRole('link', { name: 'Source 1' });
    expect(link.getAttribute('href')).toBe('https://example.com');
    expect(within(link).queryByRole('button')).toBeNull();
  });

  it('does not invent a preview for missing or legacy unnumbered evidence', () => {
    const { container } = render(<MarkdownRenderer
      content="Unsupported [Source 99], an array [2], and legacy [Source 1]."
      citations={[{ source: 'Legacy paper', text: 'No stable source number.' }]}
    />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(container.textContent).toContain('[Source 99]');
    expect(container.textContent).toContain('[2]');
  });

  it('keeps source mappings separate between messages with the same number', async () => {
    const user = userEvent.setup();
    render(<>
      <MarkdownRenderer content="First [Source 1]." citations={citations} />
      <MarkdownRenderer content="Second [Source 1]." citations={[{ id: 1, source: 'Other.pdf', text: 'Other evidence.' }]} />
    </>);
    await user.hover(screen.getAllByRole('button', { name: 'Preview source 1' })[1]);
    expect(screen.getByRole('tooltip').textContent).toContain('Other evidence.');
    expect(screen.getByRole('tooltip').textContent).not.toContain(citations[0].text);
  });
});
