import { describe, expect, it } from 'vitest';
import {
  COMPACT_TOP_NAV_MEDIA_QUERY,
  TOP_NAV_ACTIONS,
  getTopNavActionLayout,
} from './topNavContract';

describe('TopNav action layout contract', () => {
  it('keeps every action on the bar above the compact breakpoint', () => {
    const layout = getTopNavActionLayout(TOP_NAV_ACTIONS, false);

    expect(layout.inlineActionIds).toEqual([
      'new-project',
      'export',
      'theme',
      'notifications',
      'help',
      'settings',
    ]);
    expect(layout.overflowActionIds).toEqual([]);
  });

  it('collapses everything but the badged notifications control below it', () => {
    const layout = getTopNavActionLayout(TOP_NAV_ACTIONS, true);

    expect(layout.inlineActionIds).toEqual(['notifications']);
    expect(layout.overflowActionIds).toEqual([
      'new-project',
      'export',
      'theme',
      'help',
      'settings',
    ]);
  });

  it('never offers an action the workspace cannot run, at either width', () => {
    const withoutExport = TOP_NAV_ACTIONS.filter((id) => id !== 'export');

    expect(getTopNavActionLayout(withoutExport, false).inlineActionIds).not.toContain('export');
    expect(getTopNavActionLayout(withoutExport, true).overflowActionIds).toEqual([
      'new-project',
      'theme',
      'help',
      'settings',
    ]);
  });

  it('mirrors the Tailwind sm breakpoint so CSS and JS agree on what compact means', () => {
    expect(COMPACT_TOP_NAV_MEDIA_QUERY).toBe('(max-width: 39.9375rem)');
  });
});
