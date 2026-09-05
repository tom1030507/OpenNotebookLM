// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MindMapDialog from './MindMapDialog';
import type { MindMap, MindMapNode } from '@/lib/api';

const node = (id: string, label: string, children: MindMapNode[] = []): MindMapNode => ({
  id, label, children, kind: id === 'root' ? 'project' : 'topic',
  document_id: 'doc-1', detail: `About ${label}`,
});
const map: MindMap = {
  project_id: 'p1', project_name: 'Paper notes', model_used: 'test-model',
  generated_at: '2026-09-05T00:00:00Z', node_count: 5,
  root: node('root', 'Transformer', [
    node('attention', 'Attention', [node('heads', 'Multiple heads', [node('detail', 'Parallel attention')])]),
    node('results', 'Results'),
  ]),
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('mind map exploration', () => {
  it('makes partial source coverage visible', () => {
    render(<MindMapDialog map={{ ...map, source_count: 24, total_source_count: 30 }} onClose={vi.fn()} />);
    expect(screen.getByText(/24 of 30 ready sources/)).toBeTruthy();
  });
  it('folds a large map to main ideas instead of opening with tiny labels', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1000);
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400);
    const large = { ...map, root: node('root', 'Transformer', Array.from({ length: 6 }, (_, i) => (
      node(`branch-${i}`, `Main idea ${i}`, Array.from({ length: 4 }, (_, j) => node(`leaf-${i}-${j}`, `Detail ${i}-${j}`)))
    ))) };
    render(<MindMapDialog map={large} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Expand Main idea 0' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Explore Detail 0-0' })).toBeNull();
  });
  it('opens an overview and reveals deeper concepts through separate branch controls', () => {
    render(<MindMapDialog map={map} onClose={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Explore Parallel attention' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Expand Multiple heads' }));
    expect(screen.getByRole('button', { name: 'Explore Parallel attention' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse all branches' }));
    expect(screen.queryByRole('button', { name: 'Explore Multiple heads' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Expand all branches' }));
    expect(screen.getByRole('button', { name: 'Explore Parallel attention' })).toBeTruthy();
  });

  it('selects a concept without collapsing it and prepares a contextual chat question', () => {
    const ask = vi.fn();
    render(<MindMapDialog map={map} onClose={vi.fn()} onAsk={ask} />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore Attention' }));
    expect(screen.getByText('About Attention')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Explore Multiple heads' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Ask in chat' }));
    expect(ask).toHaveBeenCalledWith(
      'Explain “Attention” in the context of Transformer, using the sources in this notebook.',
    );
  });

  it('switches to a full-screen view and retains the map controls', () => {
    render(<MindMapDialog map={map} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Enter full screen' }));
    expect(screen.getByRole('button', { name: 'Exit full screen' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Fit to view' })).toBeTruthy();
  });
});
