// Mirrors the Tailwind `lg` breakpoint that decides drawer versus inline layout.
export const DESKTOP_MEDIA_QUERY = '(min-width: 64rem)';

export const WORKSPACE_PANELS = [
  { id: 'sources', label: 'Sources' },
  { id: 'conversations', label: 'Conversations' },
  { id: 'studio', label: 'Studio' },
] as const;

export type WorkspacePanelId = (typeof WORKSPACE_PANELS)[number]['id'];
export type WorkspaceContentId = WorkspacePanelId | 'main';

export type WorkspacePanelAction =
  | { type: 'toggle'; panel: WorkspacePanelId }
  | { type: 'dismiss' };

export function reduceWorkspacePanel(
  activePanel: WorkspacePanelId | null,
  action: WorkspacePanelAction,
): WorkspacePanelId | null {
  if (action.type === 'dismiss') {
    return null;
  }

  return activePanel === action.panel ? null : action.panel;
}

export function getResponsiveLayoutContract(
  activePanel: WorkspacePanelId | null,
) {
  return {
    drawerControls: [...WORKSPACE_PANELS],
    drawerPanelId: activePanel,
    drawerWidth: 'min(20rem, 90vw)',
    inlinePanelIds: WORKSPACE_PANELS.map(({ id }) => id),
    contentOrder: ['sources', 'main', 'conversations', 'studio'] as WorkspaceContentId[],
  };
}
