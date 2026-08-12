import { describe, expect, it } from 'vitest';
import {
  getResponsiveLayoutContract,
  reduceWorkspacePanel,
} from './responsiveLayoutContract';

describe('ResponsiveLayout layout contract', () => {
  it('provides three labeled drawer controls on compact screens and opens only the requested panel', () => {
    const layout = getResponsiveLayoutContract(false, 'conversations');

    expect(layout.drawerControls).toEqual([
      { id: 'sources', label: '來源' },
      { id: 'conversations', label: '對話' },
      { id: 'studio', label: '工作室' },
    ]);
    expect(layout.inlinePanelIds).toEqual([]);
    expect(layout.drawerPanelId).toBe('conversations');
    expect(layout.drawerWidth).toBe('min(20rem, 90vw)');
  });

  it('closes the active compact drawer when dismissed or another panel is selected', () => {
    expect(reduceWorkspacePanel('sources', { type: 'dismiss' })).toBeNull();
    expect(reduceWorkspacePanel('sources', { type: 'toggle', panel: 'studio' })).toBe('studio');
    expect(reduceWorkspacePanel('studio', { type: 'toggle', panel: 'studio' })).toBeNull();
  });

  it('keeps every supporting panel inline in the established desktop order', () => {
    const layout = getResponsiveLayoutContract(true, 'studio');

    expect(layout.drawerControls).toEqual([]);
    expect(layout.drawerPanelId).toBeNull();
    expect(layout.inlinePanelIds).toEqual(['sources', 'conversations', 'studio']);
    expect(layout.contentOrder).toEqual(['sources', 'main', 'conversations', 'studio']);
  });
});
