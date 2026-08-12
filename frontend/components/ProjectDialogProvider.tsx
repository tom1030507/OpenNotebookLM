'use client';

import React, { createContext, useContext, useState } from 'react';
import ProjectDialog from './ProjectDialog';

interface ProjectDialogContextValue {
  openProjectDialog: () => void;
}

const ProjectDialogContext = createContext<ProjectDialogContextValue | null>(null);

export default function ProjectDialogProvider({ children }: React.PropsWithChildren) {
  const [isOpen, setIsOpen] = useState(false);

  const openProjectDialog = () => {
    setIsOpen(true);
  };

  return (
    <ProjectDialogContext.Provider value={{ openProjectDialog }}>
      {children}
      <ProjectDialog isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </ProjectDialogContext.Provider>
  );
}

export function useProjectDialog() {
  const context = useContext(ProjectDialogContext);

  if (!context) {
    throw new Error('useProjectDialog \u5FC5\u9808\u5728 ProjectDialogProvider \u5167\u4F7F\u7528');
  }

  return context;
}
