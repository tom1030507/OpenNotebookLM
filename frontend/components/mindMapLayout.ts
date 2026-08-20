import type { MindMap, MindMapNode } from '@/lib/api';

/** Width of a node box. */
export const NODE_WIDTH = 168;
/** Height of a node box. */
export const NODE_HEIGHT = 44;
/** Distance between the left edges of two adjacent columns. */
export const COLUMN_WIDTH = 224;
/** Distance between the top edges of two adjacent rows. */
export const ROW_HEIGHT = 60;

/**
 * Smallest zoom the map is drawn at. Below this the 12px labels stop being
 * readable, so a map too wide even for this scrolls instead of shrinking.
 */
export const MIN_ZOOM = 0.4;
/** Largest zoom the map is drawn at. */
export const MAX_ZOOM = 1.5;
/** How much one press of zoom in or out changes the scale. */
export const ZOOM_STEP = 0.1;

/**
 * The zoom that fits a drawing into the width available for it.
 *
 * Opening at 1:1 is wrong on a narrow screen: the three-column map is about
 * 616px wide, so a phone shows the root and nothing else, with no hint that the
 * rest is off to the right. Fitting first, and letting the reader zoom in, puts
 * the whole shape on screen.
 *
 * @param containerWidth Width available, in CSS pixels. 0 before layout.
 * @param drawingWidth Width the map needs at 1:1.
 * @returns A scale in [MIN_ZOOM, 1], to two decimal places.
 */
export function fitZoom(containerWidth: number, drawingWidth: number): number {
  // Before the first layout the container measures 0. Shrinking to the floor on
  // that reading would make every map open tiny and then never correct itself.
  if (containerWidth <= 0 || drawingWidth <= 0) return 1;

  const scale = Math.min(1, containerWidth / drawingWidth);

  return Math.max(MIN_ZOOM, Math.round(scale * 100) / 100);
}

export interface PositionedNode {
  id: string;
  label: string;
  kind: MindMapNode['kind'];
  detail: string | null;
  documentId: string | null;
  depth: number;
  /** Left edge of the box, in canvas coordinates. */
  x: number;
  /** Top edge of the box, in canvas coordinates. */
  y: number;
  hasChildren: boolean;
  isCollapsed: boolean;
}

export interface PositionedEdge {
  fromId: string;
  toId: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

export interface MindMapGeometry {
  nodes: PositionedNode[];
  edges: PositionedEdge[];
  width: number;
  height: number;
}

interface LayoutOptions {
  /** Ids whose children are hidden. */
  collapsed?: ReadonlySet<string>;
}

/**
 * Lay a mind map out left to right: one column per level, one row per leaf.
 *
 * Rows go to leaves rather than to every node, and a parent is centred between
 * its first and last child, which is what makes a branch read as one group
 * instead of a list. Left to right rather than radial because labels are words:
 * a radial map has to rotate them, and rotated text in a scrollable panel is
 * unreadable at the sizes this panel has.
 *
 * @param root The tree's root node.
 * @param options Collapsed node ids.
 * @returns Positioned nodes and edges, plus the canvas size they need.
 */
export function layoutMindMap(
  root: MindMapNode,
  options: LayoutOptions = {},
): MindMapGeometry {
  const collapsed = options.collapsed ?? new Set<string>();
  const nodes: PositionedNode[] = [];
  const edges: PositionedEdge[] = [];
  let nextRow = 0;

  // Returns the node's y, so the parent can centre itself on its children
  // without a second pass over the tree.
  const place = (node: MindMapNode, depth: number): number => {
    const children = collapsed.has(node.id) ? [] : node.children;
    const childCentres = children.map((child) => place(child, depth + 1));

    const y = childCentres.length
      ? (childCentres[0] + childCentres[childCentres.length - 1]) / 2
      : (nextRow++) * ROW_HEIGHT;

    const positioned: PositionedNode = {
      id: node.id,
      label: node.label,
      kind: node.kind,
      detail: node.detail,
      documentId: node.document_id,
      depth,
      x: depth * COLUMN_WIDTH,
      y,
      hasChildren: node.children.length > 0,
      isCollapsed: collapsed.has(node.id) && node.children.length > 0,
    };
    nodes.push(positioned);

    children.forEach((child, index) => {
      edges.push({
        fromId: node.id,
        toId: child.id,
        fromX: positioned.x + NODE_WIDTH,
        fromY: y + NODE_HEIGHT / 2,
        toX: (depth + 1) * COLUMN_WIDTH,
        toY: childCentres[index] + NODE_HEIGHT / 2,
      });
    });

    return y;
  };

  place(root, 0);

  const width = Math.max(...nodes.map((node) => node.x)) + NODE_WIDTH;
  const height = Math.max(...nodes.map((node) => node.y)) + NODE_HEIGHT;

  return { nodes, edges, width, height };
}

/**
 * Add or remove one id from the collapsed set.
 *
 * Returns a new set rather than mutating: React compares by identity, and an
 * in-place `add` would not re-render the map.
 *
 * @param collapsed The current collapsed ids.
 * @param id The node to open or close.
 * @returns A new set with that node's state flipped.
 */
export function toggleCollapsed(
  collapsed: ReadonlySet<string>,
  id: string,
): Set<string> {
  const next = new Set(collapsed);
  if (!next.delete(id)) {
    next.add(id);
  }
  return next;
}

/** Reported by the API when the documents' structure named the topics. */
const FALLBACK_MODEL = 'fallback';

/**
 * Render a mind map as an indented Markdown list, for downloading.
 *
 * Serialised here rather than fetched again: the tree is already loaded, and a
 * second endpoint would have to rebuild it — including a second call to the
 * model, which could name different topics than the map on screen.
 *
 * @param map The mind map to write out.
 * @returns Markdown, ending in a newline.
 */
export function mindMapToMarkdown(map: MindMap): string {
  const lines = [`# ${map.project_name} mind map`, ''];

  if (!map.root.children.length) {
    lines.push('_No sources in this project yet._', '');
    return lines.join('\n');
  }

  lines.push(
    map.model_used === FALLBACK_MODEL
      ? '_Topics taken from document structure rather than from a language model._'
      : `_Topics named by ${map.model_used}._`,
    '',
  );

  const write = (node: MindMapNode, depth: number) => {
    lines.push(`${'  '.repeat(depth)}- ${node.label}`);
    node.children.forEach((child) => write(child, depth + 1));
  };
  map.root.children.forEach((branch) => write(branch, 0));

  lines.push('');
  return lines.join('\n');
}
