'use client';

import { useReducer } from 'react';

import TopNav from '@/components/layout/TopNav';
import SourcesPanel from '@/components/layout/SourcesPanel';
import ChatArea from '@/components/chat/ChatArea';
import StudioPanel from '@/components/layout/StudioPanel';
import ConversationList from '@/components/ConversationList';
import {
  desktopWorkspaceReducer,
  getDesktopWorkspaceStyle,
  initialDesktopWorkspaceState,
} from '@/components/desktopLayout';

export default function Home() {
  const [layoutState, dispatchLayout] = useReducer(
    desktopWorkspaceReducer,
    initialDesktopWorkspaceState,
  );

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top Navigation */}
      <TopNav />
      
      {/* Main Content Area */}
      <main
        data-layout="desktop-workspace"
        className="flex-1 grid min-w-0 overflow-hidden"
        style={getDesktopWorkspaceStyle(layoutState)}
      >
        {/* Left Sidebar - Sources */}
        <SourcesPanel
          isCollapsed={layoutState.sources}
          onCollapsedChange={() => {
            dispatchLayout({ type: 'toggle-panel', panel: 'sources' });
          }}
        />
        
        {/* Center - Chat Area */}
        <ChatArea />
        
        {/* Conversation List */}
        <div className="min-w-0 overflow-hidden">
          <ConversationList />
        </div>
        
        {/* Right Sidebar - Studio */}
        <StudioPanel
          isCollapsed={layoutState.studio}
          onCollapsedChange={() => {
            dispatchLayout({ type: 'toggle-panel', panel: 'studio' });
          }}
        />
      </main>
    </div>
  );
}
