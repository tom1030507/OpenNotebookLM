export const WORKSPACE_PANELS = [
  { id: 'sources', label: '來源' },
  { id: 'conversations', label: '對話' },
  { id: 'studio', label: '工作室' },
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
  isDesktop: boolean,
  activePanel: WorkspacePanelId | null,
) {
  return {
    drawerControls: isDesktop ? [] : [...WORKSPACE_PANELS],
    drawerPanelId: isDesktop ? null : activePanel,
    drawerWidth: 'min(20rem, 90vw)',
    inlinePanelIds: isDesktop ? WORKSPACE_PANELS.map(({ id }) => id) : [],
    contentOrder: isDesktop
      ? (['sources', 'main', 'conversations', 'studio'] as WorkspaceContentId[])
      : (['main'] as WorkspaceContentId[]),
  };
}
