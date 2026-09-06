// Mirrors the Tailwind `xl` breakpoint that decides drawer versus inline layout.
//
// It was `lg` (64rem/1024px), which is the width the inline layout serves
// worst: Sources, Conversations and Studio sit at their 192/184/192px floors,
// so 568px is gone before the conversation gets any, and the prose column ends
// up around 250px. The three panels only stop crowding the centre from roughly
// 1200px up, so hand 1024-1279px back to the drawer layout, which is built for
// exactly this — one panel at a time, over a full-width conversation.
export const DESKTOP_MEDIA_QUERY = '(min-width: 80rem)';

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
