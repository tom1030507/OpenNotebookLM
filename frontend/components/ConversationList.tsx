'use client';

import React, { useState } from 'react';
import { 
  Plus, 
  Trash2, 
  Edit2, 
  Check, 
  X,
  ChevronDown,
  ChevronRight
} from 'lucide-react';
import useStore from '@/store/useStore';
import { parseApiTimestamp } from '@/lib/datetime';
import { formatDistanceToNow } from 'date-fns';

interface ConversationListProps {
  /**
   * Set when the list shares the desktop sidebar with Sources. It then sizes to
   * its content (capped by its slot) instead of filling a column of its own,
   * so collapsing it hands the height back to Sources.
   */
  embedded?: boolean;
}

export default function ConversationList({ embedded = false }: ConversationListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  const {
    conversations,
    currentConversation,
    currentProject,
    selectConversation,
    createConversation,
    updateConversation,
    deleteConversation,
  } = useStore();

  const handleEdit = (id: string, currentTitle: string) => {
    setEditingId(id);
    setEditTitle(currentTitle);
  };

  const handleSaveEdit = async () => {
    if (!editingId || !editTitle.trim()) return;
    
    try {
      await updateConversation(editingId, editTitle.trim());
      setEditingId(null);
      setEditTitle('');
    } catch (error) {
      console.error('Failed to update conversation:', error);
    }
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
      const convDate = parseApiTimestamp(conv.created_at);
      
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
    <div
      className={`w-full min-w-0 overflow-hidden bg-[var(--sidebar-bg)] flex flex-col ${
        embedded ? 'min-h-0 max-h-full' : 'h-full border-l border-[var(--border)]'
      }`}
    >
      {/* Header */}
      <div className="px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="min-w-0 flex items-center gap-2">
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              aria-controls="conversation-panel-content"
              aria-expanded={!isCollapsed}
              aria-label={isCollapsed ? 'Expand conversations' : 'Collapse conversations'}
              title={isCollapsed ? 'Expand conversations' : 'Collapse conversations'}
              className="p-1 hover:bg-[var(--muted)] rounded transition-base"
            >
              {isCollapsed ? (
                <ChevronRight className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>
            <h3 className="truncate text-sm font-medium">Conversations</h3>
          </div>
          {/* One quiet control in both states. Add Source and Send are the
              screen's filled actions; a third black button here competed with
              them for the first click. */}
          <button
            onClick={handleNewConversation}
            aria-label="New Conversation"
            title="New Conversation"
            className="flex items-center gap-1 h-7 px-2 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--muted)] rounded-md transition-base"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New</span>
          </button>
        </div>
      </div>

      {/* Conversations List */}
      <div
        id="conversation-panel-content"
        role="region"
        aria-label="Conversations panel content"
        hidden={isCollapsed}
        className="min-h-0 flex-1 overflow-y-auto px-2 pb-2"
      >
          {Object.keys(groupedConversations).length === 0 ? (
            <div className="px-2 py-2 text-xs text-[var(--muted-foreground)]">
              <p>No conversations yet</p>
              <p className="mt-0.5">Start a new chat to begin</p>
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(groupedConversations).map(([group, convs]) => (
                <div key={group}>
                  <h4 className="text-xs text-[var(--muted-foreground)] mb-1 px-2">
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
                              className="flex-1 px-2 py-1 text-xs bg-[var(--card)] border border-[var(--input)] rounded focus:outline-none focus:ring-1 focus:ring-[var(--ring)]"
                              autoFocus
                            />
                            <button
                              onClick={handleSaveEdit}
                              aria-label="Save conversation name"
                              title="Save conversation name"
                              className="p-1 text-[var(--success)] hover:bg-[var(--muted)] rounded"
                            >
                              <Check className="w-3 h-3" />
                            </button>
                            <button
                              onClick={handleCancelEdit}
                              aria-label="Cancel rename"
                              title="Cancel rename"
                              className="p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] rounded"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <div
                            onClick={() => selectConversation(conv)}
                            className="flex items-start gap-2 px-2 py-1 cursor-pointer"
                          >
                            <div className="flex-1 min-w-0">
                              <p className="text-sm truncate" title={conv.title}>
                                {conv.title}
                              </p>
                              <p className="text-xs text-[var(--muted-foreground)] flex items-center mt-0.5">
                                {/* One line: in a narrow panel "2 minutes ago"
                                    otherwise wraps. */}
                                <span className="truncate">
                                  {formatDistanceToNow(parseApiTimestamp(conv.created_at), { addSuffix: true })}
                                </span>
                              </p>
                            </div>

                            {/* Overlaid rather than in flow: at opacity-0 these
                                still reserved their width, and the title lost it
                                permanently. See the same note in SourcesPanel. */}
                            <div className={`absolute right-2 top-2 flex items-center gap-1 rounded pl-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 ${
                              currentConversation?.id === conv.id
                                ? 'bg-[var(--accent-bg)]'
                                : 'bg-[var(--muted)]'
                            }`}>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleEdit(conv.id, conv.title);
                                }}
                                className="p-1 hover:bg-[var(--muted)] rounded"
                                aria-label="Rename conversation"
                                title="Rename conversation"
                              >
                                <Edit2 className="w-3 h-3" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDelete(conv.id);
                                }}
                                className="p-1 hover:bg-[var(--card)] text-[var(--error)] rounded"
                                aria-label="Delete conversation"
                                title="Delete conversation"
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
    </div>
  );
}
