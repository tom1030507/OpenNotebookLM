import { CSSProperties } from 'react';

export type CollapsibleDesktopPanel = 'sources' | 'studio';

export interface DesktopWorkspaceState {
  sources: boolean;
  studio: boolean;
}

export type DesktopWorkspaceAction =
  | {
      type: 'toggle-panel';
      panel: CollapsibleDesktopPanel;
    }
  | {
      type: 'set-panel';
      panel: CollapsibleDesktopPanel;
      collapsed: boolean;
    };

export interface DesktopWorkspaceMetrics {
  sources: number;
  center: number;
  conversations: number;
  studio: number;
  total: number;
}

interface FluidTrack {
  min: number;
  preferredViewportRatio: number;
  max: number;
}

const COLLAPSED_PANEL_WIDTH = 48;
// The left column holds Sources and, on desktop, Conversations too, so it is
// a little wider than Studio: wide enough that a source name and its error
// message read on one or two lines instead of one word per line.
const SOURCES_TRACK: FluidTrack = {
  min: 240,
  preferredViewportRatio: 0.18,
  max: 288,
};
const CONVERSATIONS_TRACK: FluidTrack = {
  min: 184,
  preferredViewportRatio: 0.13,
  max: 224,
};
const STUDIO_TRACK: FluidTrack = {
  min: 220,
  preferredViewportRatio: 0.16,
  max: 272,
};

export const initialDesktopWorkspaceState: DesktopWorkspaceState = {
  sources: false,
  studio: false,
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function resolveFluidTrack(viewportWidth: number, track: FluidTrack) {
  return clamp(
    viewportWidth * track.preferredViewportRatio,
    track.min,
    track.max,
  );
}

function toRem(value: number) {
  return `${value / 16}rem`;
}

function toFluidTrackCss(track: FluidTrack) {
  return `clamp(${toRem(track.min)}, ${track.preferredViewportRatio * 100}vw, ${toRem(track.max)})`;
}

export function desktopWorkspaceReducer(
  state: DesktopWorkspaceState,
  action: DesktopWorkspaceAction,
): DesktopWorkspaceState {
  if (action.type === 'set-panel') {
    if (state[action.panel] === action.collapsed) return state;

    return {
      ...state,
      [action.panel]: action.collapsed,
    };
  }

  return {
    ...state,
    [action.panel]: !state[action.panel],
  };
}

export function resolveDesktopWorkspaceMetrics(
  viewportWidth: number,
  state: DesktopWorkspaceState,
  hasConversationPanel = true,
): DesktopWorkspaceMetrics {
  const sources = state.sources
    ? COLLAPSED_PANEL_WIDTH
    : resolveFluidTrack(viewportWidth, SOURCES_TRACK);
  const conversations = hasConversationPanel
    ? resolveFluidTrack(viewportWidth, CONVERSATIONS_TRACK)
    : 0;
  const studio = state.studio
    ? COLLAPSED_PANEL_WIDTH
    : resolveFluidTrack(viewportWidth, STUDIO_TRACK);
  const supportingWidth = sources + conversations + studio;
  const center = Math.max(0, viewportWidth - supportingWidth);

  return {
    sources,
    center,
    conversations,
    studio,
    total: supportingWidth + center,
  };
}

export function getDesktopWorkspaceStyle(
  state: DesktopWorkspaceState,
  hasConversationPanel = true,
): CSSProperties {
  const sources = state.sources
    ? toRem(COLLAPSED_PANEL_WIDTH)
    : toFluidTrackCss(SOURCES_TRACK);
  const studio = state.studio
    ? toRem(COLLAPSED_PANEL_WIDTH)
    : toFluidTrackCss(STUDIO_TRACK);
  const conversations = hasConversationPanel
    ? toFluidTrackCss(CONVERSATIONS_TRACK)
    : '0';

  return {
    gridTemplateColumns: `${sources} minmax(0, 1fr) ${conversations} ${studio}`,
    gridTemplateRows: 'minmax(0, 1fr)',
  };
}

export const chatWorkspaceStyle: CSSProperties = {
  containerName: 'chat-workspace',
  containerType: 'inline-size',
};

export const welcomeHeroStyles: Record<
  'frame' | 'content' | 'icon' | 'glyph' | 'title' | 'actions' | 'card',
  CSSProperties
> = {
  frame: {
    paddingInline: 'clamp(1.25rem, 6cqw, 4rem)',
  },
  content: {
    width: '100%',
    maxWidth: '60rem',
  },
  icon: {
    width: 'clamp(2.5rem, 6cqw, 3rem)',
    height: 'clamp(2.5rem, 6cqw, 3rem)',
    marginBottom: 'clamp(1rem, 3cqw, 1.5rem)',
  },
  glyph: {
    width: 'clamp(2rem, 5cqw, 2.75rem)',
    height: 'clamp(2rem, 5cqw, 2.75rem)',
  },
  // An app screen's title, not a landing page's: it tops out at 32px.
  title: {
    fontSize: 'clamp(1.375rem, 4cqw, 2rem)',
  },
  actions: {
    marginTop: 'clamp(1.5rem, 5cqw, 2.5rem)',
    gap: 'clamp(0.5rem, 2cqw, 0.75rem)',
    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 15rem), 1fr))',
  },
  card: {
    padding: 'clamp(0.875rem, 2.5cqw, 1.25rem)',
  },
};
