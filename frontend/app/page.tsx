"use client";

import TopNav from '@/components/layout/TopNav';
import SourcesPanel from '@/components/layout/SourcesPanel';
import ChatArea from '@/components/chat/ChatArea';
import StudioPanel from '@/components/layout/StudioPanel';
import ConversationList from '@/components/ConversationList';
import ResponsiveLayout from '@/components/ResponsiveLayout';

export default function Home() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top Navigation */}
      <TopNav />
      
      {/* Main Content Area */}
      <ResponsiveLayout
        sidebar={<SourcesPanel />}
        conversationPanel={<ConversationList />}
        rightPanel={<StudioPanel />}
      >
        <ChatArea />
      </ResponsiveLayout>
    </div>
  );
}
