import { describe, expect, it } from 'vitest';
import {
  getResponsiveLayoutContract,
  reduceWorkspacePanel,
} from './responsiveLayoutContract';

describe('ResponsiveLayout layout contract', () => {
  it('provides three labeled drawer controls while CSS decides their visibility', () => {
    const layout = getResponsiveLayoutContract('conversations');

    expect(layout.drawerControls).toEqual([
      { id: 'sources', label: 'Sources' },
      { id: 'conversations', label: 'Conversations' },
      { id: 'studio', label: 'Studio' },
    ]);
    expect(layout.inlinePanelIds).toEqual(['sources', 'conversations', 'studio']);
    expect(layout.drawerPanelId).toBe('conversations');
    expect(layout.drawerWidth).toBe('min(20rem, 90vw)');
  });

  it('closes the active compact drawer when dismissed or another panel is selected', () => {
    expect(reduceWorkspacePanel('sources', { type: 'dismiss' })).toBeNull();
    expect(reduceWorkspacePanel('sources', { type: 'toggle', panel: 'studio' })).toBe('studio');
    expect(reduceWorkspacePanel('studio', { type: 'toggle', panel: 'studio' })).toBeNull();
  });

  it('keeps every supporting panel in the established desktop order', () => {
    const layout = getResponsiveLayoutContract('studio');

    expect(layout.drawerControls).toEqual([
      { id: 'sources', label: 'Sources' },
      { id: 'conversations', label: 'Conversations' },
      { id: 'studio', label: 'Studio' },
    ]);
    expect(layout.drawerPanelId).toBe('studio');
    expect(layout.inlinePanelIds).toEqual(['sources', 'conversations', 'studio']);
    expect(layout.contentOrder).toEqual(['sources', 'main', 'conversations', 'studio']);
  });
});
