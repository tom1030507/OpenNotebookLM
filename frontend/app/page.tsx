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
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { DESKTOP_MEDIA_QUERY } from '@/components/responsiveLayoutContract';

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
  const [outputLanguageRevision, setOutputLanguageRevision] = useState(0);
  // On desktop, conversations share the left column with Sources instead of
  // taking a fourth track: four columns left the answer about 690px wide at
  // 1440px and every panel cramped. Below `xl` they keep their own drawer.
  // Exactly one ConversationList is mounted either way.
  const isDesktop = useMediaQuery(DESKTOP_MEDIA_QUERY);
  const sourcesPanel = (
    <SourcesPanel
      isCollapsed={layoutState.sources}
      onCollapsedChange={() => {
        dispatchLayout({ type: 'toggle-panel', panel: 'sources' });
      }}
      isAddSourcesOpen={isAddSourcesOpen}
      onAddSourcesOpenChange={setIsAddSourcesOpen}
    />
  );
  const showConversationsInSidebar = isDesktop && hasProject && !layoutState.sources;

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
          desktopStyle={getDesktopWorkspaceStyle(layoutState, hasProject && !isDesktop)}
          sidebar={
            showConversationsInSidebar ? (
              <div className="flex h-full min-h-0 flex-col">
                <div className="min-h-0 flex-1">{sourcesPanel}</div>
                <div className="flex min-h-0 max-h-[38%] flex-col border-r border-t border-[var(--border)]">
                  <ConversationList embedded />
                </div>
              </div>
            ) : sourcesPanel
          }
          conversationPanel={isDesktop ? undefined : <ConversationList />}
          rightPanel={(isDrawer) => (
            <StudioPanel
              outputLanguageRevision={outputLanguageRevision}
              isCollapsed={isDrawer ? false : layoutState.studio}
              onCollapsedChange={isDrawer ? undefined : () => {
                  dispatchLayout({ type: 'toggle-panel', panel: 'studio' });
                }}
            />
          )}
        >
          <ChatArea
            onAddSourcesOpenChange={setIsAddSourcesOpen}
            outputLanguageRevision={outputLanguageRevision}
            onOutputLanguageChanged={() => setOutputLanguageRevision((value) => value + 1)}
          />
        </ResponsiveLayout>
      </div>
    </ProjectDialogProvider>
  );
}
