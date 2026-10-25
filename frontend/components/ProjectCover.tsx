import { findProjectCoverColor, projectCoverStyle } from '@/lib/projectCover';

interface ProjectCoverProps {
  emoji?: string | null;
  color?: string | null;
  className?: string;
}

export default function ProjectCover({ emoji, color, className = '' }: ProjectCoverProps) {
  const palette = findProjectCoverColor(color);

  return (
    <span
      role="img"
      aria-label={`Project cover: ${emoji || '📚'}`}
      data-cover-color={palette?.id}
      className={`project-cover inline-flex items-center justify-center rounded-lg shrink-0 ${className}`}
      style={projectCoverStyle(color)}
    >
      {emoji || '📚'}
    </span>
  );
}
