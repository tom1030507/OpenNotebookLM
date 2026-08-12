'use client';

import React, { useEffect, useReducer } from 'react';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import {
  getResponsiveLayoutContract,
  reduceWorkspacePanel,
  type WorkspacePanelId,
} from './responsiveLayoutContract';

interface ResponsiveLayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
  conversationPanel?: React.ReactNode;
  rightPanel?: React.ReactNode;
}

export default function ResponsiveLayout({
  children,
  sidebar,
  conversationPanel,
  rightPanel,
}: ResponsiveLayoutProps) {
  const isCompact = useMediaQuery('(max-width: 1023px)');
  const [activePanel, dispatch] = useReducer(reduceWorkspacePanel, null);
  const layout = getResponsiveLayoutContract(!isCompact, activePanel);
  const panels: Record<WorkspacePanelId, React.ReactNode> = {
    sources: sidebar,
    conversations: conversationPanel,
    studio: rightPanel,
  };

  useEffect(() => {
    if (!isCompact && activePanel) {
      dispatch({ type: 'dismiss' });
    }
  }, [activePanel, isCompact]);

  useEffect(() => {
    if (!activePanel) return;

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        dispatch({ type: 'dismiss' });
      }
    };

    window.addEventListener('keydown', dismissOnEscape);
    return () => window.removeEventListener('keydown', dismissOnEscape);
  }, [activePanel]);

  return (
    <div className="relative flex min-w-0 flex-1 overflow-hidden">
      <div className="absolute left-3 top-3 z-30 flex gap-2 lg:hidden">
        {layout.drawerControls.map(({ id, label }) => {
          const isOpen = layout.drawerPanelId === id;

          return (
            <button
              key={id}
              type="button"
              onClick={() => dispatch({ type: 'toggle', panel: id })}
              aria-pressed={isOpen}
              aria-label={isOpen ? `關閉${label}面板` : `開啟${label}面板`}
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
            className="absolute inset-0 z-40 bg-black/50 lg:hidden"
            onClick={() => dispatch({ type: 'dismiss' })}
          />
          <aside
            className={`absolute inset-y-0 z-50 overflow-hidden bg-[var(--background)] shadow-xl lg:hidden ${
              layout.drawerPanelId === 'studio' ? 'right-0' : 'left-0'
            }`}
            style={{ width: layout.drawerWidth }}
          >
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
