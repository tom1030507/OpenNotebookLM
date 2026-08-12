import { CSSProperties } from 'react';

export type CollapsibleDesktopPanel = 'sources' | 'studio';

export interface DesktopWorkspaceState {
  sources: boolean;
  studio: boolean;
}

export type DesktopWorkspaceAction = {
  type: 'toggle-panel';
  panel: CollapsibleDesktopPanel;
};

export interface DesktopWorkspaceMetrics {
  sources: number;
  center: number;
  conversations: number;
  studio: number;
  total: number;
}

export interface WelcomeHeroMetrics {
  contentWidth: number;
  titleSize: number;
}

interface FluidTrack {
  min: number;
  preferredViewportRatio: number;
  max: number;
}

const COLLAPSED_PANEL_WIDTH = 48;
const SOURCES_TRACK: FluidTrack = {
  min: 192,
  preferredViewportRatio: 0.15,
  max: 272,
};
const CONVERSATIONS_TRACK: FluidTrack = {
  min: 144,
  preferredViewportRatio: 0.11,
  max: 192,
};
const STUDIO_TRACK: FluidTrack = {
  min: 192,
  preferredViewportRatio: 0.15,
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
  return {
    ...state,
    [action.panel]: !state[action.panel],
  };
}

export function resolveDesktopWorkspaceMetrics(
  viewportWidth: number,
  state: DesktopWorkspaceState,
): DesktopWorkspaceMetrics {
  const sources = state.sources
    ? COLLAPSED_PANEL_WIDTH
    : resolveFluidTrack(viewportWidth, SOURCES_TRACK);
  const conversations = resolveFluidTrack(viewportWidth, CONVERSATIONS_TRACK);
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
): CSSProperties {
  const sources = state.sources
    ? toRem(COLLAPSED_PANEL_WIDTH)
    : toFluidTrackCss(SOURCES_TRACK);
  const studio = state.studio
    ? toRem(COLLAPSED_PANEL_WIDTH)
    : toFluidTrackCss(STUDIO_TRACK);

  return {
    gridTemplateColumns: `${sources} minmax(0, 1fr) ${toFluidTrackCss(CONVERSATIONS_TRACK)} ${studio}`,
  };
}

export function resolveWelcomeHeroMetrics(
  centerWidth: number,
): WelcomeHeroMetrics {
  const horizontalPadding = clamp(centerWidth * 0.06, 20, 64);

  return {
    contentWidth: Math.min(960, Math.max(0, centerWidth - horizontalPadding * 2)),
    titleSize: clamp(centerWidth * 0.03, 28, 44),
  };
}

export function getWelcomeHeroStyle(): CSSProperties {
  return {
    width: '100%',
    maxWidth: '60rem',
  };
}
