'use client';

import { useReducer, useState } from 'react';

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

export default function Home() {
  const [layoutState, dispatchLayout] = useReducer(
    desktopWorkspaceReducer,
    initialDesktopWorkspaceState,
  );
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);
  const currentProject = useStore((state) => state.currentProject);

  return (
    <ProjectDialogProvider>
      <div className="h-screen flex flex-col overflow-hidden">
        {/* Top Navigation */}
        <TopNav />

        {/* Main Content Area — drawers below `lg`, bounded grid tracks at `lg` and up */}
        <ResponsiveLayout
          desktopStyle={getDesktopWorkspaceStyle(layoutState, Boolean(currentProject))}
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
          rightPanel={
            <StudioPanel
              isCollapsed={layoutState.studio}
              onCollapsedChange={() => {
                dispatchLayout({ type: 'toggle-panel', panel: 'studio' });
              }}
            />
          }
        >
          <ChatArea onAddSourcesOpenChange={setIsAddSourcesOpen} />
        </ResponsiveLayout>
      </div>
    </ProjectDialogProvider>
  );
}
