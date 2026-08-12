'use client';

import React, { useCallback, useEffect, useReducer, useRef } from 'react';
import { useMediaQuery } from '@/hooks/useMediaQuery';
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
  const isCompact = useMediaQuery('(max-width: 1023px)');
  const [activePanel, dispatch] = useReducer(reduceWorkspacePanel, null);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerFocusControllerRef = useRef<DrawerFocusController | null>(null);
  const layout = getResponsiveLayoutContract(!isCompact, activePanel);
  const panels: Record<WorkspacePanelId, React.ReactNode> = {
    sources: sidebar,
    conversations: conversationPanel,
    studio: rightPanel,
  };

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
    if (!isCompact && activePanel) {
      dismissDrawer();
    }
  }, [activePanel, dismissDrawer, isCompact]);

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
    <div className="relative flex min-w-0 flex-1 overflow-hidden">
      <div className="absolute left-3 top-3 z-30 flex gap-2 lg:hidden">
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
      </div>

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
            aria-label={`${layout.drawerControls.find(({ id }) => id === layout.drawerPanelId)?.label}面板`}
            onKeyDown={(event) => drawerFocusController.trapTab(event)}
            className={`absolute inset-y-0 z-50 overflow-hidden bg-[var(--background)] shadow-xl lg:hidden ${
              layout.drawerPanelId === 'studio' ? 'right-0' : 'left-0'
            }`}
            style={{ width: layout.drawerWidth }}
          >
            <button
              type="button"
              aria-label={`關閉${layout.drawerControls.find(({ id }) => id === layout.drawerPanelId)?.label}面板`}
              onClick={dismissDrawer}
              className="absolute right-3 top-3 z-10 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm shadow-sm"
            >
              關閉
            </button>
            {panels[layout.drawerPanelId]}
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
          <div key={item} className="hidden shrink-0 lg:block">
            {panels[item]}
          </div>
        );
      })}
    </div>
  );
}
