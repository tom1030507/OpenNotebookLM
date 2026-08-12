'use client';

import React, { useCallback, useEffect, useReducer, useRef } from 'react';
import {
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
}: ResponsiveLayoutProps) {
  const [activePanel, dispatch] = useReducer(reduceWorkspacePanel, null);
  const drawerRef = useRef<HTMLElement>(null);
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

      <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {layout.drawerPanelId && (
          <>
            <button
              type="button"
              aria-label="關閉面板"
              tabIndex={-1}
              className="absolute inset-0 z-40 bg-black/50 lg:hidden"
              onClick={dismissDrawer}
            />
            <aside
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-label={`${activePanelLabel}面板`}
              onKeyDown={(event) => drawerFocusController.trapTab(event)}
              className={`absolute inset-y-0 z-50 flex flex-col overflow-hidden bg-[var(--background)] shadow-xl lg:hidden ${
                layout.drawerPanelId === 'studio' ? 'right-0' : 'left-0'
              }`}
              style={{ width: layout.drawerWidth }}
            >
              <header className="flex shrink-0 items-center justify-end border-b border-[var(--border)] p-3">
                <button
                  type="button"
                  aria-label={`關閉${activePanelLabel}面板`}
                  onClick={dismissDrawer}
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm shadow-sm"
                >
                  關閉
                </button>
              </header>
              <div className="min-h-0 flex-1 overflow-hidden">
                {panels[layout.drawerPanelId]}
              </div>
            </aside>
          </>
        )}

        {layout.contentOrder.map((item) => {
          if (item === 'main') {
            return (
              <main key={item} className="flex min-w-0 flex-1 flex-col">
                {children}
              </main>
            );
          }

          return (
            <div
              key={item}
              data-workspace-region={item}
              className="hidden shrink-0 lg:block"
            >
              {panels[item]}
            </div>
          );
        })}
      </div>
    </div>
  );
}
