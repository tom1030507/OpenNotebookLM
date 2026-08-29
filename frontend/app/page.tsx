'use client';

import { useEffect, useReducer, useState } from 'react';

import TopNav from '@/components/layout/TopNav';
import SourcesPanel from '@/components/layout/SourcesPanel';
import ChatArea from '@/components/chat/ChatArea';
import StudioPanel from '@/components/layout/StudioPanel';
import ConversationList from '@/components/ConversationList';
import ResponsiveLayout from '@/components/ResponsiveLayout';
import ProjectDialogProvider from '@/components/ProjectDialogProvider';
import {
  desktopWorkspaceReducer,
  getDesktopWorkspaceStyle,
  initialDesktopWorkspaceState,
} from '@/components/desktopLayout';
import useStore from '@/store/useStore';
import useDocumentStatusWatch from '@/hooks/useDocumentStatusWatch';

export default function Home() {
  const currentProject = useStore((state) => state.currentProject);
  const hasProject = Boolean(currentProject);
  const [layoutState, dispatchLayout] = useReducer(
    desktopWorkspaceReducer,
    {
      ...initialDesktopWorkspaceState,
      studio: !hasProject,
    },
  );
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);

  useEffect(() => {
    dispatchLayout({
      type: 'set-panel',
      panel: 'studio',
      collapsed: !hasProject,
    });
  }, [hasProject]);

  // Sources become queryable a while after they are uploaded, so the workspace
  // has to keep looking until they do.
  useDocumentStatusWatch();

  return (
    <ProjectDialogProvider>
      <div className="h-screen flex flex-col overflow-hidden">
        {/* Top Navigation */}
        <TopNav />

        {/* Main Content Area — drawers below `lg`, bounded grid tracks at `lg` and up */}
        <ResponsiveLayout
          desktopStyle={getDesktopWorkspaceStyle(layoutState, hasProject)}
          sidebar={
            <SourcesPanel
              isCollapsed={layoutState.sources}
              onCollapsedChange={() => {
                dispatchLayout({ type: 'toggle-panel', panel: 'sources' });
              }}
              isAddSourcesOpen={isAddSourcesOpen}
              onAddSourcesOpenChange={setIsAddSourcesOpen}
            />
          }
          conversationPanel={<ConversationList />}
          rightPanel={(isDrawer) => (
            <StudioPanel
              isCollapsed={isDrawer ? false : layoutState.studio}
              onCollapsedChange={isDrawer ? undefined : () => {
                  dispatchLayout({ type: 'toggle-panel', panel: 'studio' });
                }}
            />
          )}
        >
          <ChatArea onAddSourcesOpenChange={setIsAddSourcesOpen} />
        </ResponsiveLayout>
      </div>
    </ProjectDialogProvider>
  );
}
