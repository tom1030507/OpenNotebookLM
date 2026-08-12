'use client';

import React, { useId, useRef, useState } from 'react';
import { 
  Download, 
  X, 
  FileJson, 
  FileText, 
  FileCode,
  Loader2,
  Check
} from 'lucide-react';
import api from '@/lib/api';
import type {
  ConversationExportFormat,
  ProjectExportFormat,
} from '@/lib/api';
import useDialogFocus from '@/hooks/useDialogFocus';

interface ExportDialogProps {
  type: 'conversation' | 'project';
  id: string;
  name: string;
  onClose: () => void;
}

export default function ExportDialog({ type, id, name, onClose }: ExportDialogProps) {
  const [format, setFormat] = useState<ConversationExportFormat>('markdown');
  const [isExporting, setIsExporting] = useState(false);
  const [exportSuccess, setExportSuccess] = useState(false);
  const initialFocusRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const formats: ConversationExportFormat[] = type === 'project'
    ? ['markdown', 'json']
    : ['markdown', 'json', 'txt'];

  useDialogFocus({
    isOpen: true,
    onClose,
    dismissible: !isExporting,
    dialogRef,
    initialFocusRef,
  });

  const handleExport = async () => {
    setIsExporting(true);
    try {
      let blob: Blob;
      
      if (type === 'conversation') {
        blob = await api.exportConversation(id, format);
      } else {
        blob = await api.exportProject(id, format as ProjectExportFormat);
      }
      
      // Create download link
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${name.replace(/[^a-z0-9]/gi, '_')}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      setExportSuccess(true);
      setTimeout(() => {
        setExportSuccess(false);
        onClose();
      }, 2000);
    } catch (error) {
      console.error('Export failed:', error);
      alert('Export failed. Please try again.');
    } finally {
      setIsExporting(false);
    }
  };

  const getFormatIcon = (fmt: typeof format) => {
    switch (fmt) {
      case 'json':
        return <FileJson className="w-5 h-5" />;
      case 'markdown':
        return <FileCode className="w-5 h-5" />;
      case 'txt':
        return <FileText className="w-5 h-5" />;
    }
  };

  const getFormatDescription = (fmt: typeof format) => {
    switch (fmt) {
      case 'json':
        return 'Structured data format, ideal for developers and data processing';
      case 'markdown':
        return 'Formatted text with styling, perfect for documentation';
      case 'txt':
        return 'Plain text format, compatible with all text editors';
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-[var(--background)] rounded-lg w-full max-w-md"
      >
        {/* Header */}
        <div className="p-6 border-b border-[var(--border)]">
          <div className="flex items-center justify-between">
            <h2 id={titleId} className="text-lg font-semibold">Export {type === 'conversation' ? 'Conversation' : 'Project'}</h2>
            <button
              onClick={onClose}
              type="button"
              aria-label={'\u95dc\u9589\u532f\u51fa\u5c0d\u8a71\u6846'}
              title={'\u95dc\u9589\u532f\u51fa\u5c0d\u8a71\u6846'}
              disabled={isExporting}
              className="p-1 hover:bg-[var(--muted)] rounded transition-base"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <p className="text-sm text-[var(--muted-foreground)] mt-2">
            Export &ldquo;{name}&rdquo; to your preferred format
          </p>
        </div>

        {/* Format Selection */}
        <div className="p-6 space-y-4">
          <h3 className="text-sm font-medium mb-3">Choose export format:</h3>
          
          <div className="space-y-3">
            {formats.map((fmt) => (
              <label
                key={fmt}
                className={`flex items-start gap-3 p-4 rounded-lg border cursor-pointer transition-all ${
                  format === fmt
                    ? 'border-[var(--primary)] bg-[var(--primary)]/5'
                    : 'border-[var(--border)] hover:bg-[var(--muted)]'
                }`}
              >
                <input
                  type="radio"
                  ref={fmt === formats[0] ? initialFocusRef : undefined}
                  name="format"
                  value={fmt}
                  checked={format === fmt}
                  onChange={(e) => setFormat(e.target.value as typeof format)}
                  className="mt-1"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    {getFormatIcon(fmt)}
                    <span className="font-medium uppercase text-sm">{fmt}</span>
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {getFormatDescription(fmt)}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="p-6 border-t border-[var(--border)] flex gap-3">
          <button
            onClick={onClose}
            disabled={isExporting}
            className="flex-1 px-4 py-2 border border-[var(--border)] rounded-lg hover:bg-[var(--muted)] transition-base disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting || exportSuccess}
            className="flex-1 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-base disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {exportSuccess ? (
              <>
                <Check className="w-4 h-4" />
                <span>Exported!</span>
              </>
            ) : isExporting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Exporting...</span>
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                <span>Export</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
