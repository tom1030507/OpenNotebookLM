"use client";

import React, { useState, useEffect } from 'react';
import { 
  Plus, 
  Search,
  FileText,
  Globe,
  Youtube,
  File,
  X,
  Loader2,
  FolderOpen,
  Eye
} from 'lucide-react';
import FileUpload from '../FileUpload';
import DocumentPreview from '../DocumentPreview';
import useStore from '@/store/useStore';
import { Document } from '@/lib/api';

export default function SourcesPanel() {
  const [searchQuery, setSearchQuery] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [previewDocument, setPreviewDocument] = useState<Document | null>(null);
  
  const {
    projects,
    currentProject,
    documents,
    loadingDocuments,
    fetchProjects,
    selectProject,
    createProject,
    uploadDocument,
    createDocument,
    deleteDocument,
  } = useStore();

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleCreateProject = async () => {
    const name = prompt('Enter project name:');
    if (!name) return;
    
    setCreatingProject(true);
    try {
      const project = await createProject(name);
      selectProject(project);
    } catch (error) {
      console.error('Failed to create project:', error);
      alert('Failed to create project');
    } finally {
      setCreatingProject(false);
    }
  };

  const handleUpload = async (items: File[] | string[]) => {
    if (!currentProject) {
      alert('Please select or create a project first');
      return;
    }

    for (const item of items) {
      try {
        if (item instanceof File) {
          await uploadDocument(currentProject.id, item);
        } else {
          // Handle URL or YouTube link
          const isYouTube = item.includes('youtube.com') || item.includes('youtu.be');
          await createDocument(currentProject.id, {
            name: item,
            type: isYouTube ? 'youtube' : 'url',
            url: item,
          });
        }
      } catch (error) {
        console.error('Failed to upload:', error);
      }
    }
    
    setShowUpload(false);
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!currentProject) return;
    
    if (confirm('Are you sure you want to delete this document?')) {
      try {
        await deleteDocument(currentProject.id, docId);
      } catch (error) {
        console.error('Failed to delete document:', error);
        alert('Failed to delete document');
      }
    }
  };

  const getSourceIcon = (type: string) => {
    switch (type) {
      case 'pdf':
      case 'text':
        return <FileText className="w-4 h-4" />;
      case 'url':
        return <Globe className="w-4 h-4" />;
      case 'youtube':
        return <Youtube className="w-4 h-4" />;
      default:
        return <File className="w-4 h-4" />;
    }
  };

  // Filter documents based on search query
  const filteredDocuments = documents.filter(doc => 
    doc.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <aside className="w-80 border-r border-[var(--border)] bg-[var(--sidebar-bg)] flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--sidebar-border)]">
        <h2 className="text-base font-medium mb-3">Sources</h2>
        
        {/* Project Selector */}
        <div className="space-y-2 mb-3">
          <select
            value={currentProject?.id || ''}
            onChange={(e) => {
              const project = projects.find(p => p.id === e.target.value);
              if (project) selectProject(project);
            }}
            className="w-full px-3 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
          >
            <option value="">Select a project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          
          <button
            onClick={handleCreateProject}
            disabled={creatingProject}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 border border-[var(--border)] rounded-lg hover:bg-[var(--card)] transition-base disabled:opacity-50"
          >
            {creatingProject ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FolderOpen className="w-4 h-4" />
            )}
            <span className="text-sm">New Project</span>
          </button>
        </div>
        
        {/* Add Source Button */}
        {currentProject && (
          <button 
            onClick={() => setShowUpload(!showUpload)}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base"
          >
            <Plus className="w-4 h-4" />
            <span className="text-sm">Add Source</span>
          </button>
        )}

        {/* Search */}
        {currentProject && documents.length > 0 && (
          <div className="mt-3 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
            <input
              type="text"
              placeholder="Search sources"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
            />
          </div>
        )}
      </div>

      {/* Sources List */}
      <div className="flex-1 overflow-y-auto p-4">
        {!currentProject ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
              <FolderOpen className="w-8 h-8 text-[var(--muted-foreground)]" />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              Select or create a project to get started
            </p>
          </div>
        ) : loadingDocuments ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : filteredDocuments.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[var(--muted)] flex items-center justify-center">
              <FileText className="w-8 h-8 text-[var(--muted-foreground)]" />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              {searchQuery ? 'No sources found' : 'No sources yet'}
            </p>
            {!searchQuery && (
              <p className="text-xs text-[var(--muted-foreground)] mt-2">
                Click "Add Source" to upload PDFs, URLs, or YouTube videos
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredDocuments.map((doc) => (
              <div
                key={doc.id}
                className="p-3 bg-[var(--card)] rounded-lg border border-[var(--border)] hover:shadow-sm transition-base cursor-pointer group"
                onClick={() => setPreviewDocument(doc)}
              >
                <div className="flex items-start gap-3">
                  <div className="p-2 bg-[var(--muted)] rounded">
                    {getSourceIcon(doc.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium truncate">
                      {doc.name}
                    </h3>
                    <p className="text-xs text-[var(--muted-foreground)] mt-1">
                      {doc.status === 'processing' ? 'Processing...' : 
                       doc.status === 'completed' ? 'Ready' : doc.status}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreviewDocument(doc);
                      }}
                      className="p-1 hover:bg-[var(--muted)] rounded"
                      title="Preview"
                    >
                      <Eye className="w-3 h-3" />
                    </button>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteDocument(doc.id);
                      }}
                      className="p-1 hover:bg-[var(--muted)] rounded"
                      title="Delete"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-[var(--background)] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto">
            <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
              <h3 className="text-lg font-semibold">Add Sources</h3>
              <button
                onClick={() => setShowUpload(false)}
                className="p-1 hover:bg-[var(--muted)] rounded transition-base"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <FileUpload onUpload={handleUpload} />
          </div>
        </div>
      )}

      {/* Document Preview Modal */}
      {previewDocument && (
        <DocumentPreview
          document={previewDocument}
          onClose={() => setPreviewDocument(null)}
        />
      )}
    </aside>
  );
}
