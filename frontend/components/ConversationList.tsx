'use client';

import React, { useState } from 'react';
import { 
  MessageSquare, 
  Plus, 
  Trash2, 
  Edit2, 
  Check, 
  X,
  Clock,
  ChevronDown,
  ChevronRight
} from 'lucide-react';
import useStore from '@/store/useStore';
import { formatDistanceToNow } from 'date-fns';

export default function ConversationList() {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  const {
    conversations,
    currentConversation,
    currentProject,
    selectConversation,
    createConversation,
    deleteConversation,
  } = useStore();

  const handleEdit = (id: string, currentTitle: string) => {
    setEditingId(id);
    setEditTitle(currentTitle);
  };

  const handleSaveEdit = async () => {
    if (!editingId || !editTitle.trim()) return;
    
    // TODO: Add update conversation API call
    console.log('Update conversation:', editingId, editTitle);
    setEditingId(null);
    setEditTitle('');
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditTitle('');
  };

  const handleDelete = async (id: string) => {
    if (confirm('Are you sure you want to delete this conversation?')) {
      try {
        await deleteConversation(id);
      } catch (error) {
        console.error('Failed to delete conversation:', error);
      }
    }
  };

  const handleNewConversation = async () => {
    if (!currentProject) {
      alert('Please select a project first');
      return;
    }
    
    try {
      await createConversation(currentProject.id, 'New Conversation');
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  // Group conversations by date
  const groupedConversations = React.useMemo(() => {
    const groups: { [key: string]: typeof conversations } = {
      Today: [],
      Yesterday: [],
      'This Week': [],
      'This Month': [],
      Older: [],
    };

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    const weekAgo = new Date(today);
    weekAgo.setDate(weekAgo.getDate() - 7);
    const monthAgo = new Date(today);
    monthAgo.setMonth(monthAgo.getMonth() - 1);

    conversations.forEach(conv => {
      const convDate = new Date(conv.created_at);
      
      if (convDate >= today) {
        groups.Today.push(conv);
      } else if (convDate >= yesterday) {
        groups.Yesterday.push(conv);
      } else if (convDate >= weekAgo) {
        groups['This Week'].push(conv);
      } else if (convDate >= monthAgo) {
        groups['This Month'].push(conv);
      } else {
        groups.Older.push(conv);
      }
    });

    // Remove empty groups
    Object.keys(groups).forEach(key => {
      if (groups[key].length === 0) {
        delete groups[key];
      }
    });

    return groups;
  }, [conversations]);

  if (!currentProject) {
    return null;
  }

  return (
    <div className="w-64 bg-[var(--sidebar-bg)] border-l border-[var(--border)] flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--sidebar-border)]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1 hover:bg-[var(--muted)] rounded transition-base"
            >
              {isCollapsed ? (
                <ChevronRight className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>
            <h3 className="text-sm font-medium">Conversations</h3>
          </div>
          <button
            onClick={handleNewConversation}
            className="p-1 hover:bg-[var(--muted)] rounded transition-base"
            title="New Conversation"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
        
        {!isCollapsed && (
          <button
            onClick={handleNewConversation}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base text-sm"
          >
            <Plus className="w-4 h-4" />
            <span>New Chat</span>
          </button>
        )}
      </div>

      {/* Conversations List */}
      {!isCollapsed && (
        <div className="flex-1 overflow-y-auto p-2">
          {Object.keys(groupedConversations).length === 0 ? (
            <div className="text-center py-8">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 text-[var(--muted-foreground)]" />
              <p className="text-xs text-[var(--muted-foreground)]">
                No conversations yet
              </p>
              <p className="text-xs text-[var(--muted-foreground)] mt-1">
                Start a new chat to begin
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(groupedConversations).map(([group, convs]) => (
                <div key={group}>
                  <h4 className="text-xs font-medium text-[var(--muted-foreground)] mb-2 px-2">
                    {group}
                  </h4>
                  <div className="space-y-1">
                    {convs.map(conv => (
                      <div
                        key={conv.id}
                        className={`group relative rounded-lg transition-base ${
                          currentConversation?.id === conv.id
                            ? 'bg-[var(--accent-bg)]'
                            : 'hover:bg-[var(--muted)]'
                        }`}
                      >
                        {editingId === conv.id ? (
                          <div className="flex items-center gap-1 p-2">
                            <input
                              type="text"
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveEdit();
                                if (e.key === 'Escape') handleCancelEdit();
                              }}
                              className="flex-1 px-2 py-1 text-xs bg-[var(--background)] border border-[var(--border)] rounded focus:outline-none focus:ring-1 focus:ring-[var(--ring)]"
                              autoFocus
                            />
                            <button
                              onClick={handleSaveEdit}
                              className="p-1 text-green-600 hover:bg-green-100 rounded"
                            >
                              <Check className="w-3 h-3" />
                            </button>
                            <button
                              onClick={handleCancelEdit}
                              className="p-1 text-red-600 hover:bg-red-100 rounded"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <div
                            onClick={() => selectConversation(conv)}
                            className="flex items-start gap-2 p-2 cursor-pointer"
                          >
                            <MessageSquare className="w-4 h-4 mt-0.5 text-[var(--muted-foreground)] flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm truncate">
                                {conv.title}
                              </p>
                              <p className="text-xs text-[var(--muted-foreground)] flex items-center gap-1 mt-0.5">
                                <Clock className="w-3 h-3" />
                                {formatDistanceToNow(new Date(conv.created_at), { addSuffix: true })}
                              </p>
                            </div>
                            
                            {/* Action buttons */}
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleEdit(conv.id, conv.title);
                                }}
                                className="p-1 hover:bg-[var(--muted)] rounded"
                                title="Edit"
                              >
                                <Edit2 className="w-3 h-3" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDelete(conv.id);
                                }}
                                className="p-1 hover:bg-red-100 text-red-600 rounded"
                                title="Delete"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
