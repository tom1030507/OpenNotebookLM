// Stops just below the Tailwind `sm` breakpoint (40rem), so the compact bar and
// any `sm:` styling can never both claim the same width.
export const COMPACT_TOP_NAV_MEDIA_QUERY = '(max-width: 39.9375rem)';

// Bar order, highest priority last: the tail is what a phone-width bar keeps.
export const TOP_NAV_ACTIONS = [
  'new-project',
  'export',
  'theme',
  'notifications',
  'help',
  'settings',
] as const;

export type TopNavActionId = (typeof TOP_NAV_ACTIONS)[number];

// Seven 44px targets plus a project name do not fit an iPhone-class viewport, so
// only notifications stays inline below the breakpoint — it is the one control
// that carries state (the unread badge) rather than just an action.
const COMPACT_INLINE_ACTIONS: readonly TopNavActionId[] = ['notifications'];

export interface TopNavActionLayout {
  inlineActionIds: TopNavActionId[];
  overflowActionIds: TopNavActionId[];
}

/**
 * Splits the actions the workspace can currently run into the ones that keep
 * their own tap target on the bar and the ones that move into the overflow
 * menu. Bar order is preserved in both lists.
 */
export function getTopNavActionLayout(
  availableActionIds: readonly TopNavActionId[],
  isCompact: boolean,
): TopNavActionLayout {
  if (!isCompact) {
    return { inlineActionIds: [...availableActionIds], overflowActionIds: [] };
  }

  return {
    inlineActionIds: availableActionIds.filter((id) => COMPACT_INLINE_ACTIONS.includes(id)),
    overflowActionIds: availableActionIds.filter((id) => !COMPACT_INLINE_ACTIONS.includes(id)),
  };
}
