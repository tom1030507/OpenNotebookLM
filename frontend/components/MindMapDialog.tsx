'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Download, Minus, Plus, RotateCcw, X } from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import type { MindMap } from '@/lib/api';
import {
  COLUMN_WIDTH,
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_HEIGHT,
  NODE_WIDTH,
  ZOOM_STEP,
  fitZoom,
  layoutMindMap,
  mindMapToMarkdown,
  toggleCollapsed,
} from './mindMapLayout';

interface MindMapDialogProps {
  map: MindMap;
  onClose: () => void;
}

/** Reported by the API when the documents' structure named the topics. */
const FALLBACK_MODEL = 'fallback';

const NODE_STYLES: Record<MindMap['root']['kind'], string> = {
  project: 'bg-[var(--accent)] text-white border-transparent font-medium',
  document: 'bg-[var(--card)] border-[var(--border)] font-medium',
  topic: 'bg-[var(--secondary)] border-[var(--border)]',
};

/**
 * Width a scroll container has left for its content, inside its own padding.
 *
 * `clientWidth` includes the padding, and fitting against that left the map
 * about 48px too wide on a phone — enough to clip the last column's labels
 * mid-word.
 *
 * @param element The scroll container, or null before it mounts.
 * @returns The usable width in CSS pixels, or 0 if it cannot be measured.
 */
const contentWidth = (element: HTMLElement | null): number => {
  if (!element) return 0;

  const styles = getComputedStyle(element);
  const padding = (parseFloat(styles.paddingLeft) || 0)
    + (parseFloat(styles.paddingRight) || 0);

  return Math.max(0, element.clientWidth - padding);
};

/**
 * The project's mind map, drawn as a left-to-right tree.
 *
 * Nodes are HTML buttons positioned over an SVG that draws only the edges,
 * rather than shapes inside the SVG. Labels are words: as HTML they wrap, they
 * inherit the theme's variables, and a collapsible branch is a real button with
 * `aria-expanded` instead of a click handler on a `<rect>`.
 */
export default function MindMapDialog({ map, onClose }: MindMapDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [zoom, setZoom] = useState(1);

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  const geometry = useMemo(
    () => layoutMindMap(map.root, { collapsed }),
    [map.root, collapsed],
  );

  // Measured rather than assumed: the dialog is 896px wide on a laptop and
  // about 350 on a phone, and the map is only worth opening if it fits.
  const fitToWidth = useCallback(() => {
    setZoom(fitZoom(contentWidth(scrollRef.current), geometry.width));
  }, [geometry.width]);

  // Once, on open. Not on every geometry change: collapsing a branch narrows
  // the map, and re-fitting then would zoom the reader in behind their back.
  useEffect(fitToWidth, []); // eslint-disable-line react-hooks/exhaustive-deps

  const title = `${map.project_name} mind map`;
  // Not "no model was used": the API reports the fallback both when no provider
  // is configured and when one answered with something unusable, and claiming
  // the second case never called a model would be false.
  const provenance = map.model_used === FALLBACK_MODEL
    ? 'Topics taken from document structure rather than from a language model.'
    : `Topics named by ${map.model_used}.`;

  const download = () => {
    const blob = new Blob([mindMapToMarkdown(map)], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${title}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const changeZoom = (delta: number) => setZoom((current) => (
    Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round((current + delta) * 10) / 10))
  ));

  // Portalled to the body rather than left inside the Studio panel. The
  // mobile Studio drawer slides in with a transform, and a transformed
  // ancestor becomes the containing block for `position: fixed` — which
  // pinned this dialog to the drawer's 320px width instead of the screen.
  return createPortal(
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--background)] rounded-lg w-full max-w-4xl max-h-[85vh] flex flex-col"
      >
        <div className="flex items-start justify-between gap-3 p-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            {/* The name truncates on a narrow screen, so keep it reachable. */}
            <h2 id={titleId} title={title} className="text-lg font-semibold truncate">
              {title}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">{provenance}</p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={() => changeZoom(-ZOOM_STEP)}
              disabled={zoom <= MIN_ZOOM}
              aria-label="Zoom out"
              title="Zoom out"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base disabled:opacity-40"
            >
              <Minus className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => changeZoom(ZOOM_STEP)}
              disabled={zoom >= MAX_ZOOM}
              aria-label="Zoom in"
              title="Zoom in"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base disabled:opacity-40"
            >
              <Plus className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => { setCollapsed(new Set()); fitToWidth(); }}
              aria-label="Reset the view"
              title="Reset the view"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={download}
              aria-label="Download mind map"
              title="Download mind map"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              aria-label="Close mind map dialog"
              title="Close mind map dialog"
              className="p-2 hover:bg-[var(--muted)] rounded-lg transition-base"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto p-6">
          {map.root.children.length === 0 ? (
            <p className="text-sm text-[var(--muted-foreground)]">
              This project has no sources yet, so there is nothing to map. Add a
              source and try again.
            </p>
          ) : (
            <div
              // The transform scales the drawing; the wrapper carries the scaled
              // size so the scroll container still knows how far it reaches.
              style={{
                width: geometry.width * zoom,
                height: geometry.height * zoom,
              }}
            >
              <div
                className="relative origin-top-left"
                style={{
                  width: geometry.width,
                  height: geometry.height,
                  transform: `scale(${zoom})`,
                }}
              >
                <svg
                  aria-hidden="true"
                  width={geometry.width}
                  height={geometry.height}
                  className="absolute inset-0 pointer-events-none"
                >
                  {geometry.edges.map((edge) => (
                    <path
                      key={`${edge.fromId}-${edge.toId}`}
                      // Cubic curve with horizontal handles halfway across the
                      // gap: it leaves and arrives level with the boxes, so the
                      // line reads as attached rather than crossing them.
                      d={`M ${edge.fromX} ${edge.fromY} C ${
                        edge.fromX + (COLUMN_WIDTH - NODE_WIDTH) / 2
                      } ${edge.fromY}, ${
                        edge.toX - (COLUMN_WIDTH - NODE_WIDTH) / 2
                      } ${edge.toY}, ${edge.toX} ${edge.toY}`}
                      fill="none"
                      stroke="var(--border)"
                      strokeWidth={1.5}
                    />
                  ))}
                </svg>

                {geometry.nodes.map((node) => {
                  const shared = 'absolute flex items-center rounded-lg border px-3 text-xs text-left';
                  const style = {
                    left: node.x,
                    top: node.y,
                    width: NODE_WIDTH,
                    height: NODE_HEIGHT,
                  };

                  if (!node.hasChildren) {
                    return (
                      <div
                        key={node.id}
                        style={style}
                        title={node.label}
                        className={`${shared} ${NODE_STYLES[node.kind]}`}
                      >
                        <span className="line-clamp-2">{node.label}</span>
                      </div>
                    );
                  }

                  return (
                    <button
                      key={node.id}
                      type="button"
                      style={style}
                      title={node.label}
                      aria-expanded={!node.isCollapsed}
                      onClick={() => setCollapsed(
                        (current) => toggleCollapsed(current, node.id),
                      )}
                      className={`${shared} ${NODE_STYLES[node.kind]} hover:brightness-95 transition-base`}
                    >
                      <span className="line-clamp-2 flex-1">{node.label}</span>
                      <span aria-hidden="true" className="ml-1 shrink-0 opacity-60">
                        {node.isCollapsed ? '+' : '−'}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
