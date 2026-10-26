'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BookmarkPlus, Check, ChevronDown, ChevronRight, Download, Expand, Loader2,
  Maximize2, MessageCircle, Minimize2, Minus, Plus, UnfoldVertical,
  FoldVertical, X,
} from 'lucide-react';
import useDialogFocus from '@/hooks/useDialogFocus';
import type { MindMap, MindMapPosition } from '@/lib/api';
import {
  COLUMN_WIDTH, MAX_NODE_POSITION, MAX_ZOOM, MIN_ZOOM,
  MIND_MAP_BRANCH_COLORS, MIND_MAP_ROOT_COLOR, NODE_HEIGHT, NODE_WIDTH, ZOOM_STEP,
  collapsedBranches, fitZoom, layoutMindMap, mindMapQuestion,
  mindMapToMarkdown, mindMapToSvg, toggleCollapsed,
} from './mindMapLayout';

interface MindMapDialogProps {
  map: MindMap;
  onClose: () => void;
  onAsk?: (question: string) => void;
  onSave?: (map: MindMap) => Promise<string>;
  onLayoutChange?: (
    positions: Record<string, MindMapPosition>,
    savedNoteId?: string,
  ) => Promise<void>;
}

const branchColor = (index: number) => MIND_MAP_BRANCH_COLORS[index % MIND_MAP_BRANCH_COLORS.length] ?? '#536ec9';
const TOOL_STYLE = 'rounded-lg p-2 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-40';
const PADDING = 32;
const MAX_PNG_SIDE = 8192;
const MAX_PNG_PIXELS = 16_000_000;

async function svgToPng(svg: Blob): Promise<Blob> {
  const url = URL.createObjectURL(svg);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('Mind map SVG could not be rendered'));
      image.src = url;
    });
    // shortcut: PNG exports cap at 16 megapixels, raise only when client memory limits support larger canvases.
    const { naturalWidth, naturalHeight } = image;
    const scale = Math.min(1, MAX_PNG_SIDE / naturalWidth, MAX_PNG_SIDE / naturalHeight,
      Math.sqrt(MAX_PNG_PIXELS / (naturalWidth * naturalHeight)));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(naturalHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas is unavailable');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!png) throw new Error('PNG could not be created');
    return png;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Explore concepts on a pannable canvas without making branch toggles ask a question. */
export default function MindMapDialog({ map, onClose, onAsk, onSave, onLayoutChange }: MindMapDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const nodeDragRef = useRef<{
    id: string; pointerId: number; x: number; y: number; startX: number; startY: number; moved: boolean;
  } | null>(null);
  const positionsRef = useRef<Record<string, MindMapPosition>>(map.layout_positions ?? {});
  const savedNoteIdRef = useRef<string | undefined>(undefined);
  const layoutSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const skipNodeClickRef = useRef<string | null>(null);
  const titleId = useId();
  const instructionsId = useId();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => collapsedBranches(map.root, 2));
  const [positions, setPositions] = useState<Record<string, MindMapPosition>>(
    () => map.layout_positions ?? {},
  );
  const [zoom, setZoom] = useState(1);
  const [fullScreen, setFullScreen] = useState(false);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [layoutSaveState, setLayoutSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [exportError, setExportError] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [downloadFormat, setDownloadFormat] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [fitRequested, setFitRequested] = useState(0);

  useDialogFocus({ isOpen: true, onClose, dialogRef, initialFocusRef: closeRef });

  const geometry = useMemo(
    () => layoutMindMap(map.root, { collapsed, positions }),
    [map.root, collapsed, positions],
  );
  const allNodes = useMemo(() => layoutMindMap(map.root).nodes, [map.root]);
  const selected = allNodes.find((node) => node.id === selectedId);
  const sourceCount = map.source_count ?? new Set(allNodes.map((node) => node.documentId).filter(Boolean)).size;
  const partialCoverage = map.total_source_count != null && sourceCount < map.total_source_count;
  const title = `${map.project_name} mind map`;

  useEffect(() => {
    const nextPositions = map.layout_positions ?? {};
    positionsRef.current = nextPositions;
    setPositions(nextPositions);
    savedNoteIdRef.current = undefined;
  // Keep local drag edits when a note response refreshes the same map.
  }, [map.project_id, map.generated_at]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const download = async (format: 'markdown' | 'svg' | 'png') => {
    setExportError(false);
    setExporting(true);
    try {
      let blob: Blob;
      if (format === 'markdown') {
        blob = new Blob([mindMapToMarkdown(map)], { type: 'text/markdown' });
      } else {
        const colors = getComputedStyle(dialogRef.current ?? document.documentElement);
        const svg = new Blob([mindMapToSvg(geometry, {
          card: colors.getPropertyValue('--card').trim() || '#ffffff',
          foreground: colors.getPropertyValue('--foreground').trim() || '#0a0a0a',
          border: colors.getPropertyValue('--border').trim() || '#e4e4e0',
        })], { type: 'image/svg+xml' });
        blob = format === 'svg' ? svg : await svgToPng(svg);
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const filename = title.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, '_');
      link.href = url;
      link.download = `${filename}.${format === 'markdown' ? 'md' : format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  };

  const savePositions = (nextPositions: Record<string, MindMapPosition>) => {
    positionsRef.current = nextPositions;
    setPositions(nextPositions);
    const noteId = savedNoteIdRef.current;
    if (!onLayoutChange || (onSave && !noteId)) return;
    const save = async () => {
      setLayoutSaveState('saving');
      await onLayoutChange(nextPositions, noteId);
    };
    const queued = layoutSaveQueueRef.current.then(save, save).then(
      () => setLayoutSaveState('saved'),
      () => setLayoutSaveState('error'),
    );
    layoutSaveQueueRef.current = queued.then(() => undefined);
    return queued;
  };

  const save = async () => {
    if (!onSave) return;
    setSaveState('saving');
    try {
      const positionsAtSave = positionsRef.current;
      const mapToSave = { ...map };
      delete mapToSave.layout_positions;
      if (Object.keys(positionsAtSave).length) mapToSave.layout_positions = positionsAtSave;
      savedNoteIdRef.current = await onSave(mapToSave);
      setSaveState('saved');
      if (positionsRef.current !== positionsAtSave) savePositions(positionsRef.current);
    } catch {
      setSaveState('error');
    }
  };
  const endDrag = () => { dragRef.current = null; setDragging(false); };
  const finishNodeDrag = (nodeId: string, suppressClick: boolean) => {
    const drag = nodeDragRef.current;
    if (!drag || drag.id !== nodeId) return;
    nodeDragRef.current = null;
    setDragging(false);
    if (!drag.moved) return;
    if (suppressClick) {
      skipNodeClickRef.current = nodeId;
      window.setTimeout(() => {
        if (skipNodeClickRef.current === nodeId) skipNodeClickRef.current = null;
      }, 0);
    }
    void savePositions(positionsRef.current);
  };
  const endPointerDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (nodeDragRef.current) finishNodeDrag(nodeDragRef.current.id, event.type === 'pointerup');
    endDrag();
  };

  return createPortal(
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] ${fullScreen ? '' : 'p-2 sm:p-5'}`}>
      <div ref={dialogRef} role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby={titleId}
        className={`flex w-full min-w-0 flex-col overflow-hidden bg-[var(--card)] shadow-xl ${
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
            <label className={`${TOOL_STYLE} inline-flex items-center gap-1`}>
              <Download className="h-4 w-4" aria-hidden="true" />
              <select aria-label="Download mind map as" value={downloadFormat} disabled={exporting}
                onChange={(event) => {
                  const format = event.currentTarget.value;
                  setDownloadFormat('');
                  if (format === 'markdown' || format === 'svg' || format === 'png') {
                    void download(format);
                  }
                }} className="max-w-24 bg-transparent text-xs focus-visible:outline-none">
                <option value="" disabled>{exporting ? 'Preparing…' : 'Download as'}</option>
                <option value="markdown">Markdown</option>
                <option value="svg">SVG</option>
                <option value="png">PNG</option>
              </select>
            </label>
            {onSave && <button type="button" onClick={save}
              disabled={saveState === 'saving' || saveState === 'saved'}
              className={`${TOOL_STYLE} inline-flex items-center gap-1 text-xs disabled:opacity-50`}>
              {saveState === 'saving' ? <Loader2 className="h-4 w-4 animate-spin" />
                : saveState === 'saved' ? <Check className="h-4 w-4" />
                  : <BookmarkPlus className="h-4 w-4" />}
              <span>{saveState === 'saved' ? 'Saved to notes' : 'Save to notes'}</span>
            </button>}
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close mind map dialog" title="Close" className={TOOL_STYLE}>
              <X className="h-5 w-5" />
            </button>
          </div>
        </header>
        {saveState === 'error' && <p role="alert" className="px-4 pt-2 text-xs text-[var(--error)]">Could not save to notes. Please try again.</p>}
        {layoutSaveState === 'error' && <p role="alert" className="px-4 pt-2 text-xs text-[var(--error)]">Could not save layout. Please try again.</p>}
        {layoutSaveState === 'saving' && <p role="status" className="px-4 pt-2 text-xs text-[var(--muted-foreground)]">Saving layout…</p>}
        {layoutSaveState === 'saved' && <p role="status" className="px-4 pt-2 text-xs text-[var(--muted-foreground)]">Layout saved.</p>}
        {exportError && <p role="alert" className="px-4 pt-2 text-xs text-[var(--error)]">Could not download the mind map. Please try again.</p>}

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
            {Object.keys(positions).length > 0 && (
              <button type="button" onClick={() => { void savePositions({}); }}
                aria-label="Reset layout" title="Reset layout" className={`${TOOL_STYLE} px-3 text-xs`}>
                Reset layout
              </button>
            )}
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
          style={{ /* taste-skill-ignore: the dot grid is the canvas's pan affordance, not decoration */ backgroundImage: 'radial-gradient(var(--border) 1px, transparent 1px)', backgroundSize: '24px 24px' }}
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
          onPointerUp={endPointerDrag} onPointerCancel={endPointerDrag} onLostPointerCapture={endPointerDrag}>
          {map.root.children.length === 0 ? (
            <p className="p-8 text-sm text-[var(--muted-foreground)]">
              This project has no ready sources to map. Add a source, wait for it to finish processing, and try again.
            </p>
          ) : (
            <div className="min-h-full min-w-full" style={{
              width: geometry.width * zoom + PADDING * 2,
              height: geometry.height * zoom + PADDING * 2,
              padding: PADDING,
            }}>
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
                          title={node.label}
                          className="flex h-full w-full cursor-grab select-none items-center justify-center rounded-full border px-6 text-center text-base font-medium transition-colors hover:brightness-95 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--ring)] active:cursor-grabbing"
                          style={{
                            color: root ? 'white' : 'var(--foreground)',
                            background: root ? MIND_MAP_ROOT_COLOR : `color-mix(in srgb, ${color} 10%, var(--card))`,
                            borderColor: root ? MIND_MAP_ROOT_COLOR : `color-mix(in srgb, ${color} 45%, var(--card))`,
                            boxShadow: isSelected ? `0 0 0 3px color-mix(in srgb, ${color} 30%, transparent)` : undefined,
                            touchAction: 'none',
                          }}
                          onPointerDown={(event) => {
                            if (event.button !== 0) return;
                            event.stopPropagation();
                            event.currentTarget.setPointerCapture(event.pointerId);
                            nodeDragRef.current = {
                              id: node.id, pointerId: event.pointerId,
                              x: node.x, y: node.y, startX: event.clientX, startY: event.clientY,
                              moved: false,
                            };
                          }}
                          onPointerMove={(event) => {
                            const drag = nodeDragRef.current;
                            if (!drag || drag.id !== node.id || drag.pointerId !== event.pointerId) return;
                            const dx = event.clientX - drag.startX;
                            const dy = event.clientY - drag.startY;
                            if (!drag.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
                            drag.moved = true;
                            setDragging(true);
                            const next = {
                              ...positionsRef.current,
                              [node.id]: {
                                x: Math.max(0, Math.min(MAX_NODE_POSITION, Math.round(drag.x + dx / zoom))),
                                y: Math.max(0, Math.min(MAX_NODE_POSITION, Math.round(drag.y + dy / zoom))),
                              },
                            };
                            positionsRef.current = next;
                            setPositions(next);
                          }}
                          onPointerUp={() => finishNodeDrag(node.id, true)}
                          onPointerCancel={() => finishNodeDrag(node.id, false)}
                          onLostPointerCapture={() => finishNodeDrag(node.id, false)}
                          onClick={() => {
                            if (skipNodeClickRef.current === node.id) {
                              skipNodeClickRef.current = null;
                              return;
                            }
                            setSelectedId(node.id);
                          }}>
                          <span className="line-clamp-2 break-words">{node.label}</span>
                        </button>
                        {node.hasChildren && (
                          <button type="button" aria-label={`${node.isCollapsed ? 'Expand' : 'Collapse'} ${node.label}`} aria-expanded={!node.isCollapsed}
                            title={node.isCollapsed ? `Show ${node.childCount} branches` : 'Collapse branch'}
                            onClick={() => setCollapsed((current) => toggleCollapsed(current, node.id))}
                            className="absolute -right-4 top-1/2 flex h-8 w-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border bg-[var(--card)] text-xs focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
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
              {onAsk && <button type="button" className="flex shrink-0 items-center gap-2 rounded-full bg-[var(--primary)] px-4 py-2.5 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90"
                onClick={() => { const question = mindMapQuestion(map.root, selected.id); if (question) onAsk(question); }}>
                <MessageCircle className="h-4 w-4" /><span>Ask in chat</span><ChevronRight className="hidden h-3 w-3 sm:block" />
              </button>}
            </>
          ) : (
            <div>
              <p className="text-sm font-medium">Follow an idea</p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Select a concept to explore it. Use the circles to open or close branches.</p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Drag nodes to rearrange; drag empty space or scroll to move · Ctrl / ⌘ + scroll to zoom</p>
            </div>
          )}
          <p id={instructionsId} className="sr-only">Drag nodes to rearrange them. Drag empty space or scroll to move the canvas. Hold Ctrl or Command while scrolling to zoom. Use the zoom and fit controls to adjust the view.</p>
        </footer>
      </div>
    </div>, document.body,
  );
}
