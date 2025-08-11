"use client";

import React, { useState, useRef, useEffect } from 'react';
import { 
  Send,
  Paperclip,
  Sparkles,
  Upload,
  ChevronRight,
  Loader2
} from 'lucide-react';
import useStore from '@/store/useStore';

interface Citation {
  source: string;
  page?: number;
  text: string;
}

export default function ChatArea() {
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  const {
    currentProject,
    currentConversation,
    messages,
    documents,
    sendQuery,
    createConversation,
  } = useStore();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!inputValue.trim() || !currentProject) return;
    
    const query = inputValue.trim();
    setInputValue('');
    setIsStreaming(true);
    
    try {
      await sendQuery(query, true); // Use streaming
    } catch (error) {
      console.error('Failed to send query:', error);
    } finally {
      setIsStreaming(false);
    }
  };
  
  const handleNewConversation = async () => {
    if (!currentProject) return;
    
    try {
      await createConversation(currentProject.id, 'New Conversation');
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };
  
  // Check if ready to chat
  const hasDocuments = documents.length > 0 && documents.some(d => d.status === 'completed');
  const canChat = currentProject && hasDocuments;

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--background)]">
      {/* Chat Messages Area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center px-8">
            {/* Welcome Screen */}
            <div className="text-center max-w-2xl">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-white" />
              </div>
              
              <h2 className="text-2xl font-normal mb-3">
                新增來源即可開始使用
              </h2>
              
              <p className="text-[var(--muted-foreground)] mb-8">
                NotebookLM 提供的資訊未必正確。請查證回覆內容。
              </p>

              {/* Upload Button */}
              <button className="inline-flex items-center gap-2 px-6 py-3 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary-hover)] transition-base">
                <Upload className="w-5 h-5" />
                <span>上傳來源</span>
              </button>

              {/* Quick Actions */}
              <div className="mt-12 grid grid-cols-2 gap-4 text-left">
                <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer">
                  <h3 className="font-medium text-sm mb-1">快速開始</h3>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    上傳 PDF、網頁或 YouTube 影片
                  </p>
                </div>
                <div className="p-4 bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer">
                  <h3 className="font-medium text-sm mb-1">智能問答</h3>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    基於你的文件回答問題
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="px-4 py-6">
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex gap-3 ${
                    message.role === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {message.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center flex-shrink-0">
                      <Sparkles className="w-4 h-4 text-white" />
                    </div>
                  )}
                  
                  <div
                    className={`max-w-[70%] ${
                      message.role === 'user'
                        ? 'bg-[var(--primary)] text-white'
                        : 'bg-[var(--card)] border border-[var(--border)]'
                    } rounded-lg px-4 py-3`}
                  >
                    <p className="text-sm whitespace-pre-wrap">
                      {message.content}
                    </p>
                    
                    {/* Citations */}
                    {message.citations && message.citations.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-[var(--border)]">
                        <p className="text-xs opacity-70 mb-2">來源引用：</p>
                        {message.citations.map((citation, idx) => (
                          <div
                            key={idx}
                            className="mt-1 p-2 bg-[var(--muted)] rounded text-xs"
                          >
                            <span className="font-medium">{citation.source}</span>
                            {citation.page && (
                              <span className="opacity-70"> - 第 {citation.page} 頁</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  {message.role === 'user' && (
                    <div className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center flex-shrink-0">
                      U
                    </div>
                  )}
                </div>
              ))}
              
              {isStreaming && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-400 to-purple-600 flex items-center justify-center">
                    <Sparkles className="w-4 h-4 text-white" />
                  </div>
                  <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce" />
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce delay-100" />
                      <div className="w-2 h-2 bg-[var(--muted-foreground)] rounded-full animate-bounce delay-200" />
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="border-t border-[var(--border)] bg-[var(--card)] p-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3">
            <button className="p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded-lg transition-base">
              <Paperclip className="w-5 h-5" />
            </button>
            
            <div className="flex-1 relative">
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={canChat ? "Ask anything about your sources..." : "Add sources to start chatting"}
                className="w-full px-4 py-3 bg-[var(--background)] border border-[var(--border)] rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base text-sm"
                rows={1}
                disabled={!canChat || isStreaming}
              />
              
              {inputValue && hasDocuments && (
                <span className="absolute right-3 bottom-2 text-xs text-[var(--muted-foreground)]">
                  {documents.filter(d => d.status === 'completed').length} sources
                </span>
              )}
            </div>
            
            <button
              onClick={handleSend}
              disabled={!inputValue.trim() || !canChat || isStreaming}
              className="p-3 bg-[var(--accent)] text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-base">
              {isStreaming ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          
          {/* New Chat Button */}
          {messages.length > 0 && (
            <button 
              onClick={handleNewConversation}
              className="mt-3 flex items-center gap-1 text-xs text-[var(--primary)] hover:underline">
              <span>New Conversation</span>
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
