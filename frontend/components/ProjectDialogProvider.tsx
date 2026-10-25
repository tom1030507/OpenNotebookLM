'use client';

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import ProjectDialog from './ProjectDialog';
import type { Project } from '@/lib/api';

interface ProjectDialogContextValue {
  openProjectDialog: (project?: Project) => void;
}

const ProjectDialogContext = createContext<ProjectDialogContextValue | null>(null);

export default function ProjectDialogProvider({ children }: React.PropsWithChildren) {
  const [isOpen, setIsOpen] = useState(false);
  const [projectToEdit, setProjectToEdit] = useState<Project | null>(null);

  const openProjectDialog = useCallback((project?: Project) => {
    setProjectToEdit(project || null);
    setIsOpen(true);
  }, []);

  const closeProjectDialog = useCallback(() => {
    setIsOpen(false);
    setProjectToEdit(null);
  }, []);

  const contextValue = useMemo(() => ({ openProjectDialog }), [openProjectDialog]);

  return (
    <ProjectDialogContext.Provider value={contextValue}>
      {children}
      <ProjectDialog
        key={projectToEdit?.id || 'new'}
        isOpen={isOpen}
        onClose={closeProjectDialog}
        project={projectToEdit}
      />
    </ProjectDialogContext.Provider>
  );
}

export function useProjectDialog() {
  const context = useContext(ProjectDialogContext);

  if (!context) {
    throw new Error('useProjectDialog must be used inside ProjectDialogProvider');
  }

  return context;
}

/**
 * Read project-dialog controls when the caller may render without a provider.
 *
 * Returns:
 *   Dialog controls inside ProjectDialogProvider, otherwise null.
 */
export function useOptionalProjectDialog() {
  return useContext(ProjectDialogContext);
}
