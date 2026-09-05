'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ChevronDown, ChevronRight, Download, Expand, Maximize2, MessageCircle,
  Minimize2, Minus, Plus, UnfoldVertical, FoldVertical, X,
} from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import type { MindMap } from '@/lib/api';
import {
  COLUMN_WIDTH, MAX_ZOOM, MIN_ZOOM, NODE_HEIGHT, NODE_WIDTH, ZOOM_STEP,
  collapsedBranches, fitZoom, layoutMindMap, mindMapQuestion,
  mindMapToMarkdown, toggleCollapsed,
} from './mindMapLayout';

interface MindMapDialogProps {
  map: MindMap;
  onClose: () => void;
  onAsk?: (question: string) => void;
}

const BRANCH_COLORS = ['#536ec9', '#288778', '#b16d32', '#ae5271', '#8f63b8', '#318ba2'];
const branchColor = (index: number) => BRANCH_COLORS[index % BRANCH_COLORS.length] ?? '#536ec9';
const TOOL_STYLE = 'rounded-lg p-2 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-40';
const PADDING = 32;

/** Explore concepts on a pannable canvas without making branch toggles ask a question. */
export default function MindMapDialog({ map, onClose, onAsk }: MindMapDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const titleId = useId();
  const instructionsId = useId();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => collapsedBranches(map.root, 2));
  const [zoom, setZoom] = useState(1);
  const [fullScreen, setFullScreen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [fitRequested, setFitRequested] = useState(0);

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  const geometry = useMemo(() => layoutMindMap(map.root, { collapsed }), [map.root, collapsed]);
  const allNodes = useMemo(() => layoutMindMap(map.root).nodes, [map.root]);
  const selected = allNodes.find((node) => node.id === selectedId);
  const sourceCount = map.source_count ?? new Set(allNodes.map((node) => node.documentId).filter(Boolean)).size;
  const partialCoverage = map.total_source_count != null && sourceCount < map.total_source_count;
  const title = `${map.project_name} mind map`;

  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport || viewport.clientHeight <= 0) return;
    const scale = fitZoom(viewport.clientWidth - PADDING * 2, geometry.width,
      viewport.clientHeight - PADDING * 2, geometry.height);
    if (scale < 0.7 && geometry.nodes.some((node) => node.depth > 1)) {
      setCollapsed(collapsedBranches(map.root, 1));
      setFitRequested((n) => n + 1);
    }
    // Only choose an initial overview on open; later expansion belongs to the reader.
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fitToView = useCallback(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;
    setZoom(fitZoom(
      viewport.clientWidth - PADDING * 2, geometry.width,
      viewport.clientHeight - PADDING * 2, geometry.height,
    ));
    viewport.scrollLeft = 0;
    viewport.scrollTop = 0;
  }, [geometry.width, geometry.height]);

  // Explicit fit actions measure committed geometry, including its height.
  // Branch toggles preserve scale instead of unexpectedly zooming the reader.
  useEffect(() => { fitToView(); }, [fitRequested, fullScreen]); // eslint-disable-line react-hooks/exhaustive-deps

  const changeZoom = useCallback((delta: number) => {
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round((current + delta) * 100) / 100)));
  }, []);

  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;
    const wheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      changeZoom(event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
    };
    viewport.addEventListener('wheel', wheel, { passive: false });
    return () => viewport.removeEventListener('wheel', wheel);
  }, [changeZoom]);

  const download = () => {
    const blob = new Blob([mindMapToMarkdown(map)], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${title}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };
  const endDrag = () => { dragRef.current = null; setDragging(false); };

  return createPortal(
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-black/50 ${fullScreen ? '' : 'p-2 sm:p-5'}`}>
      <div ref={dialogRef} role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby={titleId}
        className={`flex w-full min-w-0 flex-col overflow-hidden bg-[var(--background)] shadow-2xl ${
          fullScreen ? 'h-dvh' : 'h-[92dvh] max-w-[1440px] rounded-2xl border border-[var(--border)]'
        }`}>
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3 sm:px-6">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} title={title} className="truncate text-base font-semibold">{title}</h2>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {allNodes.length} concepts{partialCoverage
                ? ` · ${sourceCount} of ${map.total_source_count} ready sources`
                : sourceCount > 0 && ` · ${sourceCount} ${sourceCount === 1 ? 'source' : 'sources'}`}
              {map.model_used === 'fallback' && ' · From document structure'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button type="button" onClick={() => setFullScreen((value) => !value)}
              aria-label={fullScreen ? 'Exit full screen' : 'Enter full screen'}
              title={fullScreen ? 'Exit full screen' : 'Enter full screen'} className={TOOL_STYLE}>
              {fullScreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
            <button type="button" onClick={download} aria-label="Download mind map" title="Download Markdown" className={TOOL_STYLE}>
              <Download className="h-4 w-4" />
            </button>
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close mind map dialog" title="Close" className={TOOL_STYLE}>
              <X className="h-5 w-5" />
            </button>
          </div>
        </header>

        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--card)] px-3 py-1.5 sm:px-5">
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => changeZoom(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM}
              aria-label="Zoom out" title="Zoom out" className={TOOL_STYLE}><Minus className="h-4 w-4" /></button>
            <output aria-label="Zoom level" className="w-12 text-center text-xs tabular-nums text-[var(--muted-foreground)]">{Math.round(zoom * 100)}%</output>
            <button type="button" onClick={() => changeZoom(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM}
              aria-label="Zoom in" title="Zoom in" className={TOOL_STYLE}><Plus className="h-4 w-4" /></button>
            <button type="button" onClick={fitToView} aria-label="Fit to view" title="Fit to view" className={TOOL_STYLE}>
              <Expand className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => { setCollapsed(new Set()); setFitRequested((n) => n + 1); }}
              aria-label="Expand all branches" title="Expand all branches" className={TOOL_STYLE}>
              <UnfoldVertical className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => { setCollapsed(collapsedBranches(map.root, 1)); setFitRequested((n) => n + 1); }}
              aria-label="Collapse all branches" title="Collapse all branches" className={TOOL_STYLE}>
              <FoldVertical className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div ref={scrollRef} role="region" aria-label="Mind map canvas" aria-describedby={instructionsId} tabIndex={0}
          className={`min-h-0 flex-1 overflow-auto overscroll-contain ${dragging ? 'cursor-grabbing select-none' : 'cursor-grab'}`}
          style={{ backgroundImage: 'radial-gradient(var(--border) 1px, transparent 1px)', backgroundSize: '24px 24px' }}
          onPointerDown={(event) => {
            if (event.pointerType === 'touch' || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
            const viewport = event.currentTarget;
            dragRef.current = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
            viewport.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            const start = dragRef.current;
            if (!start) return;
            event.currentTarget.scrollLeft = start.left + start.x - event.clientX;
            event.currentTarget.scrollTop = start.top + start.y - event.clientY;
          }}
          onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}>
          {map.root.children.length === 0 ? (
            <p className="p-8 text-sm text-[var(--muted-foreground)]">
              This project has no ready sources to map. Add a source, wait for it to finish processing, and try again.
            </p>
          ) : (
            <div className="flex min-h-full min-w-full items-center justify-center" style={{ width: geometry.width * zoom + PADDING * 2, height: geometry.height * zoom + PADDING * 2 }}>
              <div style={{ width: geometry.width * zoom, height: geometry.height * zoom }}>
                <div className="relative origin-top-left" style={{ width: geometry.width, height: geometry.height, transform: `scale(${zoom})` }}>
                  <svg aria-hidden="true" width={geometry.width} height={geometry.height} className="pointer-events-none absolute inset-0 overflow-visible">
                    {geometry.edges.map((edge) => (
                      <path key={`${edge.fromId}-${edge.toId}`}
                        d={`M ${edge.fromX} ${edge.fromY} C ${edge.fromX + (COLUMN_WIDTH - NODE_WIDTH) / 2} ${edge.fromY}, ${edge.toX - (COLUMN_WIDTH - NODE_WIDTH) / 2} ${edge.toY}, ${edge.toX} ${edge.toY}`}
                        fill="none" stroke={branchColor(edge.branchIndex)} strokeWidth={2} strokeOpacity={0.6} />
                    ))}
                  </svg>
                  {geometry.nodes.map((node) => {
                    const color = branchColor(node.branchIndex);
                    const root = node.depth === 0;
                    const isSelected = selectedId === node.id;
                    return (
                      <div key={node.id} className="absolute" style={{ left: node.x, top: node.y, width: NODE_WIDTH, height: NODE_HEIGHT }}>
                        <button type="button" aria-label={`Explore ${node.label}`} aria-pressed={isSelected}
                          title={node.label} onClick={() => setSelectedId(node.id)}
                          className="flex h-full w-full cursor-pointer items-center justify-center rounded-full border px-6 text-center text-base font-medium shadow-sm transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--ring)]"
                          style={{
                            color: root ? 'white' : 'var(--foreground)',
                            background: root ? '#4057a4' : `color-mix(in srgb, ${color} 10%, var(--card))`,
                            borderColor: root ? '#4057a4' : `color-mix(in srgb, ${color} 45%, var(--card))`,
                            boxShadow: isSelected ? `0 0 0 3px color-mix(in srgb, ${color} 30%, transparent)` : undefined,
                          }}><span className="line-clamp-2 break-words">{node.label}</span></button>
                        {node.hasChildren && (
                          <button type="button" aria-label={`${node.isCollapsed ? 'Expand' : 'Collapse'} ${node.label}`} aria-expanded={!node.isCollapsed}
                            title={node.isCollapsed ? `Show ${node.childCount} branches` : 'Collapse branch'}
                            onClick={() => setCollapsed((current) => toggleCollapsed(current, node.id))}
                            className="absolute -right-4 top-1/2 flex h-8 w-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border bg-[var(--card)] text-xs shadow-sm focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
                            style={{ borderColor: color, color: 'var(--foreground)' }}>
                            {node.isCollapsed ? <span>{node.childCount}</span> : <ChevronDown className="h-4 w-4" />}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        <footer className="flex min-h-[88px] shrink-0 items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--card)] px-4 py-3 sm:px-6">
          {selected ? (
            <>
              <div className="min-w-0" aria-live="polite">
                <p className="text-sm font-semibold">{selected.label}</p>
                <p className="mt-1 max-h-24 overflow-y-auto text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {selected.kind === 'document' ? 'Explore the concepts from this source.' : selected.detail || 'Explore this concept with a question grounded in your sources.'}
                </p>
              </div>
              {onAsk && <button type="button" className="flex shrink-0 items-center gap-2 rounded-full bg-[var(--primary)] px-4 py-2.5 text-xs font-medium text-white hover:opacity-90"
                onClick={() => { const question = mindMapQuestion(map.root, selected.id); if (question) onAsk(question); }}>
                <MessageCircle className="h-4 w-4" /><span>Ask in chat</span><ChevronRight className="hidden h-3 w-3 sm:block" />
              </button>}
            </>
          ) : (
            <div>
              <p className="text-sm font-medium">Follow an idea</p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Select a concept to explore it. Use the circles to open or close branches.</p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Drag or scroll to move · Ctrl / ⌘ + scroll to zoom</p>
            </div>
          )}
          <p id={instructionsId} className="sr-only">Drag or scroll to move. Hold Ctrl or Command while scrolling to zoom. Use the zoom and fit controls to adjust the view.</p>
        </footer>
      </div>
    </div>, document.body,
  );
}
