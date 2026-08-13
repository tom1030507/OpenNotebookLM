'use client';

import React, { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  DESKTOP_MEDIA_QUERY,
  getResponsiveLayoutContract,
  reduceWorkspacePanel,
  type WorkspacePanelId,
} from './responsiveLayoutContract';
import { DrawerFocusController } from './drawerFocusController';

interface ResponsiveLayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
  conversationPanel?: React.ReactNode;
  rightPanel?: React.ReactNode;
  /**
   * Grid track sizing for the desktop layout. Applied unconditionally but only
   * takes effect at `lg` and up, where the container becomes a grid; below that
   * the container is a flex row with the active panel promoted to a drawer.
   * Track order matches `contentOrder`: sources, centre, conversations, studio.
   */
  desktopStyle?: React.CSSProperties;
}

const FOCUSABLE_DRAWER_ELEMENTS = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getDrawerFocusableElements(drawer: HTMLElement | null) {
  if (!drawer) return [];

  return Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE_DRAWER_ELEMENTS)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  );
}

export default function ResponsiveLayout({
  children,
  sidebar,
  conversationPanel,
  rightPanel,
  desktopStyle,
}: ResponsiveLayoutProps) {
  const [activePanel, dispatch] = useReducer(reduceWorkspacePanel, null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerFocusControllerRef = useRef<DrawerFocusController | null>(null);
  const layout = getResponsiveLayoutContract(activePanel);
  const panels: Record<WorkspacePanelId, React.ReactNode> = {
    sources: sidebar,
    conversations: conversationPanel,
    studio: rightPanel,
  };
  const activePanelLabel = layout.drawerControls.find(
    ({ id }) => id === layout.drawerPanelId,
  )?.label;

  if (!drawerFocusControllerRef.current) {
    drawerFocusControllerRef.current = new DrawerFocusController(
      () => getDrawerFocusableElements(drawerRef.current),
      () => document.activeElement as HTMLElement | null,
    );
  }

  const drawerFocusController = drawerFocusControllerRef.current;
  const dismissDrawer = useCallback(() => {
    drawerFocusController.restoreTriggerFocus();
    dispatch({ type: 'dismiss' });
  }, [drawerFocusController]);

  useEffect(() => {
    if (!activePanel) return;

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        dismissDrawer();
      }
    };

    window.addEventListener('keydown', dismissOnEscape);
    return () => window.removeEventListener('keydown', dismissOnEscape);
  }, [activePanel, dismissDrawer]);

  useEffect(() => {
    if (activePanel) {
      drawerFocusController.focusInitialElement();
    }
  }, [activePanel, drawerFocusController]);

  // CSS owns the breakpoint, so a drawer opened while compact would otherwise
  // survive into the desktop layout as hidden-but-focusable dialog markup.
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;

    const desktopQuery = window.matchMedia(DESKTOP_MEDIA_QUERY);
    const clearDrawerOnDesktop = () => {
      if (!desktopQuery.matches) return;

      drawerFocusController.forgetTrigger();
      dispatch({ type: 'dismiss' });
    };

    clearDrawerOnDesktop();
    desktopQuery.addEventListener('change', clearDrawerOnDesktop);
    return () => desktopQuery.removeEventListener('change', clearDrawerOnDesktop);
  }, [drawerFocusController]);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <nav
        aria-label="工作區面板"
        className="flex shrink-0 gap-2 border-b border-[var(--border)] bg-[var(--card)] p-3 lg:hidden"
      >
        {layout.drawerControls.map(({ id, label }) => {
          const isOpen = layout.drawerPanelId === id;

          return (
            <button
              key={id}
              type="button"
              onClick={(event) => {
                if (isOpen) {
                  dismissDrawer();
                  return;
                }

                drawerFocusController.rememberTrigger(event.currentTarget);
                dispatch({ type: 'toggle', panel: id });
              }}
              aria-pressed={isOpen}
              aria-label={isOpen ? `${label}面板已開啟` : `開啟${label}面板`}
              className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm shadow-sm"
            >
              {label}
            </button>
          );
        })}
      </nav>

      <div
        data-layout="desktop-workspace"
        style={desktopStyle}
        className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden lg:grid"
      >
        {layout.drawerPanelId && (
          <button
            type="button"
            aria-label="關閉面板"
            tabIndex={-1}
            className="absolute inset-0 z-40 bg-black/50 lg:hidden"
            onClick={dismissDrawer}
          />
        )}

        {layout.contentOrder.map((item) => {
          if (item === 'main') {
            return (
              <main key={item} className="flex min-w-0 flex-1 flex-col">
                {children}
              </main>
            );
          }

          // One mount per panel: the active one is promoted to a drawer in
          // place, so opening it never duplicates its state or its fetches.
          const isDrawer = layout.drawerPanelId === item;

          return (
            <div
              key={item}
              ref={isDrawer ? drawerRef : undefined}
              data-workspace-region={item}
              role={isDrawer ? 'dialog' : undefined}
              aria-modal={isDrawer ? 'true' : undefined}
              aria-label={isDrawer ? `${activePanelLabel}面板` : undefined}
              onKeyDown={isDrawer ? (event) => drawerFocusController.trapTab(event) : undefined}
              style={
                isDrawer
                  ? ({ '--workspace-drawer-width': layout.drawerWidth } as React.CSSProperties)
                  : undefined
              }
              className={
                isDrawer
                  ? `absolute inset-y-0 z-50 flex w-[var(--workspace-drawer-width)] flex-col overflow-hidden bg-[var(--background)] shadow-xl lg:static lg:z-auto lg:block lg:w-auto lg:shrink-0 lg:overflow-visible lg:shadow-none ${
                      item === 'studio' ? 'right-0' : 'left-0'
                    }`
                  : 'hidden shrink-0 lg:block'
              }
            >
              {isDrawer && (
                <header className="flex shrink-0 items-center justify-end border-b border-[var(--border)] p-3 lg:hidden">
                  <button
                    type="button"
                    aria-label={`關閉${activePanelLabel}面板`}
                    onClick={dismissDrawer}
                    className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm shadow-sm"
                  >
                    關閉
                  </button>
                </header>
              )}
              <div className={isDrawer ? 'min-h-0 flex-1 overflow-hidden' : 'contents'}>
                {panels[item]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
