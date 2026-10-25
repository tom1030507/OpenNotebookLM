import type { CSSProperties } from 'react';

export const PROJECT_COVER_EMOJIS = ['📚', '🧠', '🔬', '🌿', '🚀', '🎨', '💡', '🌊'] as const;

export const PROJECT_COVER_COLORS = [
  { id: 'blue', label: 'Blue', lightBackground: '#dbeafe', lightForeground: '#1e3a8a', darkBackground: '#1e3a8a', darkForeground: '#dbeafe' },
  { id: 'violet', label: 'Violet', lightBackground: '#ede9fe', lightForeground: '#4c1d95', darkBackground: '#4c1d95', darkForeground: '#ede9fe' },
  { id: 'rose', label: 'Rose', lightBackground: '#ffe4e6', lightForeground: '#9f1239', darkBackground: '#9f1239', darkForeground: '#ffe4e6' },
  { id: 'amber', label: 'Amber', lightBackground: '#fef3c7', lightForeground: '#92400e', darkBackground: '#92400e', darkForeground: '#fef3c7' },
  { id: 'emerald', label: 'Emerald', lightBackground: '#d1fae5', lightForeground: '#065f46', darkBackground: '#065f46', darkForeground: '#d1fae5' },
  { id: 'teal', label: 'Teal', lightBackground: '#ccfbf1', lightForeground: '#115e59', darkBackground: '#115e59', darkForeground: '#ccfbf1' },
  { id: 'slate', label: 'Slate', lightBackground: '#e2e8f0', lightForeground: '#334155', darkBackground: '#334155', darkForeground: '#e2e8f0' },
] as const;

export type ProjectCoverColor = (typeof PROJECT_COVER_COLORS)[number]['id'];


export const findProjectCoverColor = (color?: string | null) =>
  PROJECT_COVER_COLORS.find((item) => item.id === color);

export const projectCoverStyle = (color?: string | null): CSSProperties | undefined => {
  const palette = findProjectCoverColor(color);
  return palette ? {
    '--cover-light-background': palette.lightBackground,
    '--cover-light-foreground': palette.lightForeground,
    '--cover-dark-background': palette.darkBackground,
    '--cover-dark-foreground': palette.darkForeground,
  } as CSSProperties : undefined;
};
