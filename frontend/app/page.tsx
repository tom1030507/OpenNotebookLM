"use client";

import { useState } from 'react';
import TopNav from '@/components/layout/TopNav';
import SourcesPanel from '@/components/layout/SourcesPanel';
import ChatArea from '@/components/chat/ChatArea';
import StudioPanel from '@/components/layout/StudioPanel';
import ConversationList from '@/components/ConversationList';

export default function Home() {
  const [isAddSourcesOpen, setIsAddSourcesOpen] = useState(false);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top Navigation */}
      <TopNav />
      
      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Sources */}
        <SourcesPanel
          isAddSourcesOpen={isAddSourcesOpen}
          onAddSourcesOpenChange={setIsAddSourcesOpen}
        />
        
        {/* Center - Chat Area */}
        <ChatArea onAddSourcesOpenChange={setIsAddSourcesOpen} />
        
        {/* Conversation List */}
        <ConversationList />
        
        {/* Right Sidebar - Studio */}
        <StudioPanel />
      </div>
    </div>
  );
}
