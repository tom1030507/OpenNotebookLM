"use client";

import TopNav from '@/components/layout/TopNav';
import SourcesPanel from '@/components/layout/SourcesPanel';
import ChatArea from '@/components/chat/ChatArea';
import StudioPanel from '@/components/layout/StudioPanel';

export default function Home() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top Navigation */}
      <TopNav />
      
      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Sources */}
        <SourcesPanel />
        
        {/* Center - Chat Area */}
        <ChatArea />
        
        {/* Right Sidebar - Studio */}
        <StudioPanel />
      </div>
    </div>
  );
}
