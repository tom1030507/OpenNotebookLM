// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const originalPointerCapture = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'setPointerCapture');
const originalCanvasContext = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'getContext');
const originalCanvasToBlob = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'toBlob');

function installPointerEvents() {
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.pointerType = init.pointerType ?? 'mouse';
    }
  }
  vi.stubGlobal('PointerEvent', TestPointerEvent);
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', {
    configurable: true, value: vi.fn(),
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalPointerCapture) Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', originalPointerCapture);
  else Reflect.deleteProperty(HTMLElement.prototype, 'setPointerCapture');
  if (originalCanvasContext) Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', originalCanvasContext);
  else Reflect.deleteProperty(HTMLCanvasElement.prototype, 'getContext');
  if (originalCanvasToBlob) Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', originalCanvasToBlob);
  else Reflect.deleteProperty(HTMLCanvasElement.prototype, 'toBlob');
});

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

  it('drags a node without panning the canvas and still pans on empty space', async () => {
    installPointerEvents();
    const onLayoutChange = vi.fn().mockResolvedValue(undefined);
    render(<MindMapDialog map={map} onClose={vi.fn()} onLayoutChange={onLayoutChange} />);
    const canvas = screen.getByRole('region', { name: 'Mind map canvas' });
    const nodeButton = screen.getByRole('button', { name: 'Explore Attention' });

    fireEvent.pointerDown(nodeButton, { pointerId: 1, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(nodeButton, { pointerId: 1, clientX: 70, clientY: 40 });
    fireEvent.pointerUp(screen.getByRole('button', { name: 'Explore Attention' }), {
      pointerId: 1, button: 0, clientX: 70, clientY: 40,
    });

    expect(screen.getByRole('button', { name: 'Explore Attention' }).parentElement?.style.left).toBe('352px');
    expect(canvas.scrollLeft).toBe(0);
    await waitFor(() => expect(onLayoutChange).toHaveBeenCalledWith(expect.objectContaining({
      attention: expect.objectContaining({ x: 352 }),
    }), undefined));

    fireEvent.pointerDown(canvas, { pointerId: 2, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(canvas, { pointerId: 2, clientX: 75, clientY: 80 });
    fireEvent.pointerUp(canvas, { pointerId: 2, button: 0, clientX: 75, clientY: 80 });

    expect(canvas.scrollLeft).toBe(25);
    expect(canvas.scrollTop).toBe(20);
  });

  it('keeps the canvas origin fixed when a drag expands its bounds', async () => {
    installPointerEvents();
    render(<MindMapDialog map={map} onClose={vi.fn()} />);
    const canvas = screen.getByRole('region', { name: 'Mind map canvas' });
    const frame = canvas.firstElementChild as HTMLDivElement;
    const initialWidth = Number.parseFloat(frame.style.width);
    const nodeButton = screen.getByRole('button', { name: 'Explore Multiple heads' });

    fireEvent.pointerDown(nodeButton, { pointerId: 1, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(nodeButton, { pointerId: 1, clientX: 510, clientY: 50 });
    fireEvent.pointerUp(screen.getByRole('button', { name: 'Explore Multiple heads' }), {
      pointerId: 1, button: 0, clientX: 510, clientY: 50,
    });

    expect(Number.parseFloat(frame.style.width)).toBeGreaterThan(initialWidth);
    expect(frame.style.paddingLeft).toBe('32px');
    expect(frame.className).not.toContain('justify-center');
  });

  it('saves current positions and keeps updating the saved map', async () => {
    installPointerEvents();
    const onSave = vi.fn().mockResolvedValue('saved-map');
    const onLayoutChange = vi.fn().mockResolvedValue(undefined);
    render(<MindMapDialog map={map} onClose={vi.fn()} onSave={onSave} onLayoutChange={onLayoutChange} />);
    const dragNode = async (startX: number, startY: number, endX: number, endY: number) => {
      const nodeButton = screen.getByRole('button', { name: 'Explore Attention' });
      fireEvent.pointerDown(nodeButton, { pointerId: 1, button: 0, clientX: startX, clientY: startY });
      fireEvent.pointerMove(nodeButton, { pointerId: 1, clientX: endX, clientY: endY });
      fireEvent.pointerUp(screen.getByRole('button', { name: 'Explore Attention' }), {
        pointerId: 1, button: 0, clientX: endX, clientY: endY,
      });
    };

    await dragNode(10, 10, 70, 40);
    expect(onLayoutChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save to notes' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      layout_positions: { attention: { x: 352, y: 30 } },
    })));
    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();

    await dragNode(70, 40, 100, 50);
    await waitFor(() => expect(onLayoutChange).toHaveBeenCalledWith(
      { attention: { x: 382, y: 40 } }, 'saved-map',
    ));
  });

  it('resets saved node positions and persists the empty layout', async () => {
    const onLayoutChange = vi.fn().mockResolvedValue(undefined);
    render(<MindMapDialog
      map={{ ...map, layout_positions: { attention: { x: 500, y: 200 } } }}
      onClose={vi.fn()}
      onLayoutChange={onLayoutChange}
    />);
    const nodeButton = screen.getByRole('button', { name: 'Explore Attention' });
    expect(nodeButton.parentElement?.style.left).toBe('500px');

    fireEvent.click(screen.getByRole('button', { name: 'Reset layout' }));

    expect(nodeButton.parentElement?.style.left).toBe('292px');
    await waitFor(() => expect(onLayoutChange).toHaveBeenLastCalledWith({}, undefined));
  });

  it('downloads the map as Markdown or SVG with CJK labels', async () => {
    const blobs: Blob[] = [];
    const downloads: string[] = [];
    class TestURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:map-${blobs.length}`;
      }
      static revokeObjectURL() {}
    }
    vi.stubGlobal('URL', TestURL);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(this.download);
    });
    render(<MindMapDialog
      map={{ ...map, project_name: '研究 & 概念', root: node('root', '研究 & 概念', [node('topic', '注意力')]) }}
      onClose={vi.fn()}
    />);
    const format = screen.getByRole('combobox', { name: 'Download mind map as' });

    fireEvent.change(format, { target: { value: 'markdown' } });
    expect(blobs.at(-1)?.type).toBe('text/markdown');
    expect(downloads.at(-1)).toBe('研究 & 概念 mind map.md');

    fireEvent.change(format, { target: { value: 'svg' } });
    expect(blobs.at(-1)?.type).toBe('image/svg+xml');
    expect(downloads.at(-1)).toBe('研究 & 概念 mind map.svg');
  });

  it('renders SVG as a PNG download', async () => {
    const blobs: Blob[] = [];
    const canvasSizes: Array<[number, number]> = [];
    class TestURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:map-${blobs.length}`;
      }
      static revokeObjectURL() {}
    }
    class TestImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      naturalWidth = 600;
      naturalHeight = 160;
      set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    }
    vi.stubGlobal('URL', TestURL);
    vi.stubGlobal('Image', TestImage);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
      configurable: true,
      value: vi.fn(function (this: HTMLCanvasElement) {
        canvasSizes.push([this.width, this.height]);
        return { drawImage: vi.fn() };
      }),
    });
    Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', {
      configurable: true,
      value: (callback: BlobCallback) => callback(new Blob(['png'], { type: 'image/png' })),
    });
    render(<MindMapDialog map={map} onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole('combobox', { name: 'Download mind map as' }), {
      target: { value: 'png' },
    });

    await waitFor(() => expect(blobs.some((blob) => blob.type === 'image/png')).toBe(true));
    expect(canvasSizes).toEqual([[600, 160]]);
  });
});
