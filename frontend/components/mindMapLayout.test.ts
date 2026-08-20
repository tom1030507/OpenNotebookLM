import { describe, expect, it } from 'vitest';
import {
  COLUMN_WIDTH,
  MIN_ZOOM,
  NODE_HEIGHT,
  NODE_WIDTH,
  ROW_HEIGHT,
  fitZoom,
  layoutMindMap,
  mindMapToMarkdown,
  toggleCollapsed,
} from './mindMapLayout';
import type { MindMap, MindMapNode } from '@/lib/api';

const node = (
  id: string,
  label: string,
  kind: MindMapNode['kind'],
  children: MindMapNode[] = [],
): MindMapNode => ({
  id,
  label,
  kind,
  detail: null,
  document_id: null,
  children,
});

const tree = (): MindMapNode =>
  node('root', 'Notebook', 'project', [
    node('doc-1', 'First source', 'document', [
      node('doc-1-topic-0', 'Alpha', 'topic'),
      node('doc-1-topic-1', 'Beta', 'topic'),
    ]),
    node('doc-2', 'Second source', 'document', [
      node('doc-2-topic-0', 'Gamma', 'topic'),
    ]),
  ]);

const map = (root: MindMapNode, modelUsed = 'test-model'): MindMap => ({
  project_id: 'project-1',
  // The API roots the tree in the project, so the two always agree.
  project_name: root.label,
  generated_at: '2026-08-20T00:00:00Z',
  model_used: modelUsed,
  node_count: 6,
  root,
});

describe('layoutMindMap', () => {
  it('places a lone root without any rows below it', () => {
    const laid = layoutMindMap(node('root', 'Empty', 'project'));

    expect(laid.nodes).toHaveLength(1);
    expect(laid.nodes[0].x).toBe(0);
    expect(laid.edges).toEqual([]);
  });

  it('puts each level in its own column', () => {
    const laid = layoutMindMap(tree());

    const byId = new Map(laid.nodes.map((n) => [n.id, n]));
    expect(byId.get('root')!.x).toBe(0);
    expect(byId.get('doc-1')!.x).toBe(COLUMN_WIDTH);
    expect(byId.get('doc-1-topic-0')!.x).toBe(COLUMN_WIDTH * 2);
  });

  it('gives every leaf its own row', () => {
    const laid = layoutMindMap(tree());

    const leaves = ['doc-1-topic-0', 'doc-1-topic-1', 'doc-2-topic-0'];
    const rows = laid.nodes.filter((n) => leaves.includes(n.id)).map((n) => n.y);
    expect(rows).toEqual([0, ROW_HEIGHT, ROW_HEIGHT * 2]);
  });

  it('centres a parent against the children it spans', () => {
    const laid = layoutMindMap(tree());

    const byId = new Map(laid.nodes.map((n) => [n.id, n]));
    // Alpha at row 0, Beta at row 1, so their document sits between them.
    expect(byId.get('doc-1')!.y).toBe(ROW_HEIGHT / 2);
    // Midway between its own two children, not between the rows they span:
    // a parent lines up with what it points at.
    expect(byId.get('root')!.y).toBe((ROW_HEIGHT / 2 + ROW_HEIGHT * 2) / 2);
  });

  it('draws one edge per parent-child pair', () => {
    const laid = layoutMindMap(tree());

    expect(laid.edges).toHaveLength(5);
    const edge = laid.edges.find((e) => e.toId === 'doc-1-topic-0')!;
    expect(edge.fromId).toBe('doc-1');
    // Drawable endpoints: out of the parent's right edge, into the child's left.
    expect(edge.fromX).toBe(COLUMN_WIDTH + NODE_WIDTH);
    expect(edge.toX).toBe(COLUMN_WIDTH * 2);
  });

  it('hides the descendants of a collapsed node', () => {
    const laid = layoutMindMap(tree(), { collapsed: new Set(['doc-1']) });

    const ids = laid.nodes.map((n) => n.id);
    expect(ids).toContain('doc-1');
    expect(ids).not.toContain('doc-1-topic-0');
    expect(ids).toContain('doc-2-topic-0');
  });

  it('marks which nodes have hidden children, so they can be reopened', () => {
    const laid = layoutMindMap(tree(), { collapsed: new Set(['doc-1']) });

    const byId = new Map(laid.nodes.map((n) => [n.id, n]));
    expect(byId.get('doc-1')!.isCollapsed).toBe(true);
    expect(byId.get('doc-1')!.hasChildren).toBe(true);
    expect(byId.get('doc-2')!.isCollapsed).toBe(false);
    expect(byId.get('doc-2-topic-0')!.hasChildren).toBe(false);
  });

  it('sizes the canvas to hold every node it laid out', () => {
    const laid = layoutMindMap(tree());

    expect(laid.width).toBe(COLUMN_WIDTH * 2 + NODE_WIDTH);
    expect(laid.height).toBe(ROW_HEIGHT * 2 + NODE_HEIGHT);
  });

  it('leaves room for a lone root rather than collapsing to nothing', () => {
    const laid = layoutMindMap(node('root', 'Empty', 'project'));

    expect(laid.width).toBe(NODE_WIDTH);
    expect(laid.height).toBe(NODE_HEIGHT);
  });
});

describe('toggleCollapsed', () => {
  it('collapses a node that was open', () => {
    expect(toggleCollapsed(new Set(), 'doc-1')).toEqual(new Set(['doc-1']));
  });

  it('reopens a node that was collapsed', () => {
    expect(toggleCollapsed(new Set(['doc-1']), 'doc-1')).toEqual(new Set());
  });

  it('does not modify the set it was given', () => {
    const collapsed = new Set(['doc-1']);

    toggleCollapsed(collapsed, 'doc-2');

    expect(collapsed).toEqual(new Set(['doc-1']));
  });
});

describe('mindMapToMarkdown', () => {
  it('writes the project as the heading and the branches as nested bullets', () => {
    expect(mindMapToMarkdown(map(tree()))).toContain(
      '- First source\n  - Alpha\n  - Beta\n- Second source\n  - Gamma',
    );
  });

  it('titles the document after the project', () => {
    expect(mindMapToMarkdown(map(tree())).split('\n')[0]).toBe('# Notebook mind map');
  });

  it('says which model named the topics', () => {
    expect(mindMapToMarkdown(map(tree(), 'claude-opus'))).toContain('claude-opus');
  });

  it('says so plainly when the topics came from document structure', () => {
    const markdown = mindMapToMarkdown(map(tree(), 'fallback'));

    expect(markdown).toMatch(/document structure/i);
    expect(markdown).not.toContain('fallback');
  });

  it('handles a project with no sources', () => {
    const markdown = mindMapToMarkdown(map(node('root', 'Empty', 'project')));

    expect(markdown).toContain('# Empty mind map');
    expect(markdown).toMatch(/no sources/i);
  });
});

describe('fitZoom', () => {
  it('leaves a map that already fits at its natural size', () => {
    expect(fitZoom(900, 616)).toBe(1);
  });

  it('never magnifies a small map to fill the space', () => {
    expect(fitZoom(2000, 200)).toBe(1);
  });

  it('shrinks a map to the width it has', () => {
    // A phone-width dialog against the three-column map: without this the map
    // opens showing only the root, with everything else off-screen.
    expect(fitZoom(320, 616)).toBeCloseTo(0.52, 2);
  });

  it('stops shrinking at the smallest readable zoom', () => {
    expect(fitZoom(100, 5000)).toBe(MIN_ZOOM);
  });

  it('keeps the natural size when the container has not been measured yet', () => {
    // The first render happens before layout, so the container reports 0.
    expect(fitZoom(0, 616)).toBe(1);
  });
});
