import type { MindMap, MindMapNode, MindMapPosition } from '@/lib/api';

/** Width of a node box. */
export const NODE_WIDTH = 208;
/** Height of a node box. */
export const NODE_HEIGHT = 52;
/** Distance between the left edges of two adjacent columns. */
export const COLUMN_WIDTH = 292;
/** Distance between the top edges of two adjacent rows. */
export const ROW_HEIGHT = 68;

/**
 * Smallest overview scale. Readers can zoom in and pan when a map is too large.
 */
export const MIN_ZOOM = 0.4;
/** Largest zoom the map is drawn at. */
export const MAX_ZOOM = 2;
export const MAX_NODE_POSITION = 10_000;
/** How much one press of zoom in or out changes the scale. */
export const ZOOM_STEP = 0.1;
export const MIND_MAP_BRANCH_COLORS = [
  '#536ec9', '#288778', '#b16d32', '#ae5271', '#8f63b8', '#318ba2',
];
export const MIND_MAP_ROOT_COLOR = '#4057a4';

/**
 * Fit a drawing into the available width and optional height.
 *
 * @param containerWidth Width available, in CSS pixels. 0 before layout.
 * @param drawingWidth Width the map needs at 1:1.
 * @param containerHeight Height available, in CSS pixels.
 * @param drawingHeight Height the map needs at 1:1.
 * @returns A scale in [MIN_ZOOM, 1], to two decimal places.
 */
export function fitZoom(
  containerWidth: number,
  drawingWidth: number,
  containerHeight?: number,
  drawingHeight?: number,
): number {
  // Before the first layout the container measures 0. Shrinking to the floor on
  // that reading would make every map open tiny and then never correct itself.
  if (containerWidth <= 0 || drawingWidth <= 0) return 1;

  const heightScale = containerHeight && drawingHeight
    ? containerHeight / drawingHeight : 1;
  const scale = Math.min(1, containerWidth / drawingWidth, heightScale);

  return Math.max(MIN_ZOOM, Math.round(scale * 100) / 100);
}

export interface PositionedNode {
  id: string;
  label: string;
  kind: MindMapNode['kind'];
  detail: string | null;
  documentId: string | null;
  depth: number;
  /** Inherited from the top-level branch, independent of its visible rows. */
  branchIndex: number;
  /** Left edge of the box, in canvas coordinates. */
  x: number;
  /** Top edge of the box, in canvas coordinates. */
  y: number;
  hasChildren: boolean;
  isCollapsed: boolean;
  childCount: number;
}

export interface PositionedEdge {
  fromId: string;
  toId: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  branchIndex: number;
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
  /** Saved coordinates override the computed positions for matching ids. */
  positions?: Readonly<Record<string, MindMapPosition>>;
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
  const place = (node: MindMapNode, depth: number, branchIndex: number): number => {
    const children = collapsed.has(node.id) ? [] : node.children;
    const childCentres = children.map((child, index) => (
      place(child, depth + 1, depth === 0 ? index : branchIndex)
    ));

    const y = childCentres.length
      ? (childCentres[0] + childCentres[childCentres.length - 1]) / 2
      : (nextRow++) * ROW_HEIGHT;
    const savedPosition = options.positions?.[node.id];

    const positioned: PositionedNode = {
      id: node.id,
      label: node.label,
      kind: node.kind,
      detail: node.detail,
      documentId: node.document_id,
      depth,
      branchIndex,
      x: savedPosition?.x ?? depth * COLUMN_WIDTH,
      y: savedPosition?.y ?? y,
      hasChildren: node.children.length > 0,
      isCollapsed: collapsed.has(node.id) && node.children.length > 0,
      childCount: node.children.length,
    };
    nodes.push(positioned);

    children.forEach((child, index) => {
      edges.push({
        fromId: node.id,
        toId: child.id,
        fromX: positioned.x + NODE_WIDTH,
        fromY: positioned.y + NODE_HEIGHT / 2,
        toX: options.positions?.[child.id]?.x ?? (depth + 1) * COLUMN_WIDTH,
        toY: (options.positions?.[child.id]?.y ?? childCentres[index]) + NODE_HEIGHT / 2,
        branchIndex: depth === 0 ? index : branchIndex,
      });
    });

    return y;
  };

  place(root, 0, -1);

  const width = Math.max(...nodes.map((node) => node.x)) + NODE_WIDTH;
  const height = Math.max(...nodes.map((node) => node.y)) + NODE_HEIGHT;

  return { nodes, edges, width, height };
}

export interface MindMapSvgTheme {
  card: string;
  foreground: string;
  border: string;
}

const DEFAULT_SVG_THEME: MindMapSvgTheme = {
  card: '#ffffff', foreground: '#0a0a0a', border: '#e4e4e0',
};

function escapeXml(text: string): string {
  const replacements: Record<string, string> = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;',
  };
  return text.replace(/[&<>"']/g, (char) => replacements[char]);
}

function mixHex(color: string, background: string, weight: number): string {
  const hex = /^#([\da-f]{6})$/i;
  const foregroundMatch = color.match(hex);
  const backgroundMatch = background.match(hex);
  if (!foregroundMatch || !backgroundMatch) return color;
  const foreground = foregroundMatch[1];
  const backdrop = backgroundMatch[1];
  const channels = [0, 2, 4].map((index) => Math.round(
    parseInt(foreground.slice(index, index + 2), 16) * weight
    + parseInt(backdrop.slice(index, index + 2), 16) * (1 - weight),
  ));
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

function labelLines(label: string): string[] {
  const widthOf = (char: string) => /[^\u0000-\u00ff]/u.test(char)
    ? 16
    : /[il.,'!| ]/.test(char) ? 4 : /[MW@#]/.test(char) ? 13 : 8;
  const maxWidth = NODE_WIDTH - 48;
  const lines = [''];
  const widths = [0];
  for (const char of Array.from(label)) {
    const width = widthOf(char);
    const line = lines.length - 1;
    if (widths[line] + width > maxWidth && lines[line]) {
      lines.push(char);
      widths.push(width);
    } else {
      lines[line] += char;
      widths[line] += width;
    }
  }
  if (lines.length > 2) {
    lines.length = 2;
    while (widths[1] > maxWidth - 16) {
      const chars = Array.from(lines[1]);
      widths[1] -= widthOf(chars.pop() ?? '');
      lines[1] = chars.join('');
    }
    lines[1] += '…';
  }
  return lines;
}

/** Render the current geometry as a self-contained SVG download. */
export function mindMapToSvg(
  geometry: MindMapGeometry,
  theme: MindMapSvgTheme = DEFAULT_SVG_THEME,
): string {
  const edgePadding = Math.ceil((COLUMN_WIDTH - NODE_WIDTH) / 2) + 2;
  const width = geometry.width + edgePadding * 2;
  const height = geometry.height + edgePadding * 2;
  const edges = geometry.edges.map((edge) => {
    const color = MIND_MAP_BRANCH_COLORS[
      edge.branchIndex % MIND_MAP_BRANCH_COLORS.length
    ] ?? MIND_MAP_BRANCH_COLORS[0];
    const curve = (COLUMN_WIDTH - NODE_WIDTH) / 2;
    return `<path d="M ${edge.fromX} ${edge.fromY} C ${edge.fromX + curve} ${edge.fromY}, ${edge.toX - curve} ${edge.toY}, ${edge.toX} ${edge.toY}" fill="none" stroke="${color}" stroke-width="2" stroke-opacity="0.6"/>`;
  }).join('');
  const nodes = geometry.nodes.map((node) => {
    const color = MIND_MAP_BRANCH_COLORS[
      node.branchIndex % MIND_MAP_BRANCH_COLORS.length
    ] ?? MIND_MAP_BRANCH_COLORS[0];
    const root = node.depth === 0;
    const fill = root ? MIND_MAP_ROOT_COLOR : mixHex(color, theme.card, 0.1);
    const stroke = root ? MIND_MAP_ROOT_COLOR : mixHex(color, theme.card, 0.45);
    const textColor = root ? '#ffffff' : theme.foreground;
    const centerX = node.x + NODE_WIDTH / 2;
    const centerY = node.y + NODE_HEIGHT / 2;
    const lines = labelLines(node.label);
    const firstDy = -((lines.length - 1) * 9);
    const text = lines.map((line, index) => (
      `<tspan x="${centerX}" dy="${index === 0 ? firstDy : 18}">${escapeXml(line)}</tspan>`
    )).join('');
    return `<g><rect x="${node.x}" y="${node.y}" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="26" fill="${fill}" stroke="${stroke}"/><text x="${centerX}" y="${centerY}" fill="${textColor}" font-family="system-ui, sans-serif" font-size="16" font-weight="500" text-anchor="middle" dominant-baseline="middle">${text}</text></g>`;
  }).join('');

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="-${edgePadding} -${edgePadding} ${width} ${height}"><defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="${escapeXml(theme.border)}"/></pattern></defs><rect width="100%" height="100%" fill="${escapeXml(theme.card)}"/><rect width="100%" height="100%" fill="url(#grid)"/>${edges}${nodes}</svg>`;
}

/** Collect expandable branches at or below a depth, keeping the root visible. */
export function collapsedBranches(root: MindMapNode, minimumDepth: number): Set<string> {
  const ids = new Set<string>();
  const visit = (node: MindMapNode, depth: number) => {
    if (node.children.length && depth >= minimumDepth) ids.add(node.id);
    node.children.forEach((child) => visit(child, depth + 1));
  };
  visit(root, 0);
  return ids;
}

/** Keep the parent concepts with a question so repeated leaf labels have context. */
export function mindMapQuestion(root: MindMapNode, nodeId: string): string | null {
  const find = (node: MindMapNode, path: string[]): string[] | null => {
    const next = [...path, node.label];
    if (node.id === nodeId) return next;
    for (const child of node.children) {
      const result = find(child, next);
      if (result) return result;
    }
    return null;
  };
  const path = find(root, []);
  if (!path) return null;
  const label = path.pop();
  const context = path.length ? ` in the context of ${path.join(' → ')}` : '';
  return `Explain “${label}”${context}, using the sources in this notebook.`;
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

  if (map.source_count != null && map.total_source_count != null && map.source_count < map.total_source_count) {
    lines.push(`_Covers ${map.source_count} of ${map.total_source_count} ready sources._`, '');
  }
  if (map.root.label !== map.project_name) lines.push(`## ${map.root.label}`, '');
  if (map.root.detail) lines.push(map.root.detail, '');

  const write = (node: MindMapNode, depth: number) => {
    lines.push(`${'  '.repeat(depth)}- ${node.label}`);
    if (node.detail) lines.push(`${'  '.repeat(depth + 1)}${node.detail}`);
    node.children.forEach((child) => write(child, depth + 1));
  };
  map.root.children.forEach((branch) => write(branch, 0));

  lines.push('');
  return lines.join('\n');
}
