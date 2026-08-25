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

describe('BrandLogo', () => {
  it('shows the selected F mark decoratively beside the login page product name', () => {
    const { container } = render(<LoginPage />);

    const logo = container.querySelector('[data-brand-logo="true"]');
    expect(screen.queryByRole('img', { name: 'OpenNotebookLM logo' })).toBeNull();
    expect(logo?.getAttribute('aria-hidden')).toBe('true');
    expect(logo?.getAttribute('viewBox')).toBe('0 0 64 64');
    expect(container.querySelector('image')?.getAttribute('href')).toBe(
      '/brand-logo-f.png',
    );
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
});
