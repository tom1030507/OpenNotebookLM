import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';

import Home from '@/app/page';
import SourcesPanel from '@/components/layout/SourcesPanel';
import StudioPanel from '@/components/layout/StudioPanel';
import {
  desktopWorkspaceReducer,
  getDesktopWorkspaceStyle,
  getWelcomeHeroStyle,
  initialDesktopWorkspaceState,
  resolveDesktopWorkspaceMetrics,
  resolveWelcomeHeroMetrics,
} from '@/components/desktopLayout';

describe('desktop workspace layout', () => {
  test.each([1024, 1440, 1920])(
    'keeps the center dominant without horizontal overflow at %ipx',
    (viewportWidth) => {
      const metrics = resolveDesktopWorkspaceMetrics(
        viewportWidth,
        initialDesktopWorkspaceState,
      );
      const supportingWidths = [
        metrics.sources,
        metrics.conversations,
        metrics.studio,
      ];

      expect(metrics.total).toBe(viewportWidth);
      expect(metrics.center).toBeGreaterThan(Math.max(...supportingWidths));
      expect(metrics.center).toBeGreaterThanOrEqual(400);
      expect(metrics.sources).toBeGreaterThanOrEqual(192);
      expect(metrics.sources).toBeLessThanOrEqual(272);
      expect(metrics.conversations).toBeGreaterThanOrEqual(144);
      expect(metrics.conversations).toBeLessThanOrEqual(192);
      expect(metrics.studio).toBeGreaterThanOrEqual(192);
      expect(metrics.studio).toBeLessThanOrEqual(272);
    },
  );

  test('renders the production workspace with the bounded fluid track contract', () => {
    const style = getDesktopWorkspaceStyle(initialDesktopWorkspaceState);
    const markup = renderToStaticMarkup(createElement(Home));

    expect(style.gridTemplateColumns).toContain('minmax(0, 1fr)');
    expect(markup).toContain(`grid-template-columns:${style.gridTemplateColumns}`);
    expect(markup).toContain('data-layout="desktop-workspace"');
  });

  test.each([
    ['sources', SourcesPanel],
    ['studio', StudioPanel],
  ] as const)(
    'toggles and restores the %s panel while its content stays mounted',
    (panel, Panel) => {
      const collapsedState = desktopWorkspaceReducer(initialDesktopWorkspaceState, {
        type: 'toggle-panel',
        panel,
      });
      const collapsedMarkup = renderToStaticMarkup(
        createElement(Panel, {
          isCollapsed: collapsedState[panel],
          onCollapsedChange: () => undefined,
        }),
      );

      expect(collapsedMarkup).toContain('aria-expanded="false"');
      expect(collapsedMarkup).toContain(`id="${panel}-panel-content"`);
      expect(collapsedMarkup).toContain('hidden=""');
      expect(collapsedMarkup).toContain(`data-panel-state="collapsed"`);

      const restoredState = desktopWorkspaceReducer(collapsedState, {
        type: 'toggle-panel',
        panel,
      });
      const restoredMarkup = renderToStaticMarkup(
        createElement(Panel, {
          isCollapsed: restoredState[panel],
          onCollapsedChange: () => undefined,
        }),
      );

      expect(restoredState[panel]).toBe(false);
      expect(restoredMarkup).toContain('aria-expanded="true"');
      expect(restoredMarkup).not.toContain('hidden=""');
      expect(restoredMarkup).toContain(`data-panel-state="expanded"`);
    },
  );

  test('keeps collapsed panels mounted in the production grid and releases space to chat', () => {
    const collapsedState = desktopWorkspaceReducer(
      desktopWorkspaceReducer(initialDesktopWorkspaceState, {
        type: 'toggle-panel',
        panel: 'sources',
      }),
      { type: 'toggle-panel', panel: 'studio' },
    );
    const expanded = resolveDesktopWorkspaceMetrics(
      1024,
      initialDesktopWorkspaceState,
    );
    const collapsed = resolveDesktopWorkspaceMetrics(1024, collapsedState);

    expect(collapsed.sources).toBe(48);
    expect(collapsed.studio).toBe(48);
    expect(collapsed.center).toBeGreaterThan(expanded.center);
    expect(collapsed.total).toBe(1024);
  });

  test('scales the welcome hierarchy with the available center width', () => {
    const compact = resolveWelcomeHeroMetrics(496);
    const wide = resolveWelcomeHeroMetrics(1184);
    const style = getWelcomeHeroStyle();

    expect(compact.contentWidth).toBeGreaterThanOrEqual(400);
    expect(wide.contentWidth).toBeGreaterThan(compact.contentWidth);
    expect(wide.titleSize).toBeGreaterThan(compact.titleSize);
    expect(wide.contentWidth).toBeLessThanOrEqual(960);
    expect(style.width).toBe('100%');
    expect(style.maxWidth).toBe('60rem');
  });
});
