// @vitest-environment jsdom

import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import LoginPage from '@/app/login/page';
import BrandLogo from './BrandLogo';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

afterEach(cleanup);

/**
 * Follow the `url(#id)` a mark paints with back to the definition answering it
 * inside that same `<svg>`. A reference that dangles renders as an unpainted
 * hole, which the markup alone would not show.
 *
 * Attributes are read off the elements rather than matched with a selector:
 * jsdom's selector engine does not match `[fill^="url(#"]` against SVG.
 */
const resolveGradient = (mark: Element): SVGElement => {
  const elements = Array.from(mark.querySelectorAll('*'));

  const painted = elements.find(
    (element) => element.getAttribute('fill')?.startsWith('url(#'),
  );
  expect(painted, 'nothing in the mark paints from a gradient').toBeDefined();

  const id = painted!.getAttribute('fill')!.slice('url(#'.length, -1);
  const gradient = elements.find(
    (element) => element.tagName === 'linearGradient' && element.id === id,
  );
  expect(gradient, `no linearGradient answers to ${id}`).toBeDefined();

  return gradient as SVGElement;
};

describe('BrandLogo', () => {
  it('shows the mark decoratively beside the login page product name', () => {
    const { container } = render(<LoginPage />);

    const logo = container.querySelector('[data-brand-logo="true"]');
    expect(screen.queryByRole('img', { name: 'OpenNotebookLM logo' })).toBeNull();
    expect(logo?.getAttribute('aria-hidden')).toBe('true');
    expect(logo?.getAttribute('viewBox')).toBe('0 0 24 24');
  });

  it('keeps its label semantics authoritative over conflicting SVG props', () => {
    const { container } = render(
      <BrandLogo
        label="OpenNotebookLM logo"
        role="presentation"
        aria-hidden="true"
      />,
    );
    const logo = container.querySelector('[data-brand-logo="true"]');

    expect(logo?.getAttribute('role')).toBe('img');
    expect(logo?.getAttribute('aria-label')).toBe('OpenNotebookLM logo');
    expect(logo?.getAttribute('aria-hidden')).toBeNull();
  });

  /**
   * The mark this replaced was a raster behind an `<image href>`, so every
   * place it rendered waited on a request for it. Drawing it means the logo
   * cannot arrive late or fail to arrive.
   */
  it('draws the mark rather than fetching a raster for it', () => {
    const { container } = render(<BrandLogo />);

    expect(container.querySelector('image')).toBeNull();
    expect(container.querySelectorAll('circle')).toHaveLength(6);
    expect(container.querySelectorAll('path')).toHaveLength(5);
  });

  it('paints from the theme tokens, so it needs no light tile in dark mode', () => {
    const { container } = render(<BrandLogo />);
    const mark = container.querySelector('[data-brand-logo="true"]')!;

    const stops = Array.from(resolveGradient(mark).querySelectorAll('stop')).map(
      (stop) => stop.getAttribute('stop-color'),
    );

    expect(stops).toEqual(['var(--primary)', 'var(--accent)']);
  });

  /**
   * The chat welcome, the streaming row and the nav can all be on screen at
   * once. Two marks sharing a gradient id would leave the second one blank.
   */
  it('gives every instance its own gradient id, so marks sharing a page all paint', () => {
    const { container } = render(
      <>
        <BrandLogo label="first" />
        <BrandLogo label="second" />
      </>,
    );

    const [first, second] = Array.from(
      container.querySelectorAll('[data-brand-logo="true"]'),
    );

    expect(resolveGradient(first).id).not.toEqual(resolveGradient(second).id);
  });

  /**
   * Every node has to sit inside the viewBox with its full radius, or the mark
   * is silently clipped at whatever size it is set.
   */
  it('keeps every node inside the artboard', () => {
    const { container } = render(<BrandLogo />);

    const nodes = Array.from(container.querySelectorAll('circle'));
    expect(nodes).not.toHaveLength(0);

    for (const node of nodes) {
      const cx = Number(node.getAttribute('cx'));
      const cy = Number(node.getAttribute('cy'));
      const r = Number(node.getAttribute('r'));

      expect(cx - r).toBeGreaterThanOrEqual(0);
      expect(cy - r).toBeGreaterThanOrEqual(0);
      expect(cx + r).toBeLessThanOrEqual(24);
      expect(cy + r).toBeLessThanOrEqual(24);
    }
  });
});
