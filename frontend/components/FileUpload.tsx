'use client';

import React, { useState, useCallback, useRef } from 'react';
import {
  Upload,
  X,
  File,
  FileSpreadsheet,
  Link,
  Presentation,
  Youtube,
  BookOpen,
  FileText,
  Loader2,
} from 'lucide-react';
import {
  getUploadFileError,
  SUPPORTED_UPLOAD_FILE_EXTENSIONS,
} from '@/lib/uploadValidation';

interface FileUploadProps {
  onUpload: (files: File[] | string[]) => Promise<void>;
  accept?: string;
  multiple?: boolean;
  maxSize?: number; // in MB
  onUploadingChange?: (isUploading: boolean) => void;
  onAddText?: (title: string, text: string) => Promise<void>;
}

export default function FileUpload({ 
  onUpload, 
  accept = SUPPORTED_UPLOAD_FILE_EXTENSIONS.join(','),
  multiple = false,
  maxSize = 10,
  onUploadingChange,
  onAddText,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [urlInput, setUrlInput] = useState('');
  const [textTitle, setTextTitle] = useState('');
  const [textInput, setTextInput] = useState('');
  const [uploadType, setUploadType] = useState<'file' | 'url' | 'youtube' | 'text'>('file');
  const [errors, setErrors] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const uploadInFlightRef = useRef(false);

  const startUpload = () => {
    if (isUploading || uploadInFlightRef.current) return false;

    uploadInFlightRef.current = true;
    setIsUploading(true);
    onUploadingChange?.(true);
    return true;
  };

  const finishUpload = () => {
    uploadInFlightRef.current = false;
    setIsUploading(false);
    onUploadingChange?.(false);
  };

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const validateAndAddFiles = (newFiles: File[]) => {
    const errors: string[] = [];
    const validFiles: File[] = [];

    const candidateFiles = multiple ? newFiles : newFiles.slice(0, 1);

    candidateFiles.forEach(file => {
      const error = getUploadFileError(
        file,
        maxSize,
        files.map(existingFile => existingFile.name),
      );
      if (error) {
        errors.push(error);
        return;
      }

      validFiles.push(file);
    });

    setErrors(errors);
    if (validFiles.length > 0) {
      const newFileList = multiple ? [...files, ...validFiles] : validFiles;
      setFiles(newFileList);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files);
    validateAndAddFiles(droppedFiles);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files);
      validateAndAddFiles(selectedFiles);
    }
  };

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index));
  };

  const handleUrlSubmit = async () => {
    if (isUploading || uploadInFlightRef.current) return;

    if (!urlInput.trim()) {
      setErrors(['Please enter a valid URL']);
      return;
    }

    try {
      new URL(urlInput);
    } catch {
      setErrors(['Please enter a valid URL']);
      return;
    }

    if (!startUpload()) return;

    try {
      await onUpload([urlInput]);
      setUrlInput('');
      setErrors([]);
    } catch {
      setErrors(['Upload failed. Please check the URL and try again.']);
    } finally {
      finishUpload();
    }
  };

  const handleTextSubmit = async () => {
    if (!onAddText || !textTitle.trim() || !textInput.trim()) return;

    if (new Blob([textInput]).size > maxSize * 1024 * 1024) {
      setErrors([`Text exceeds ${maxSize}MB limit`]);
      return;
    }

    if (!startUpload()) return;

    try {
      await onAddText(textTitle.trim(), textInput);
      setTextTitle('');
      setTextInput('');
      setErrors([]);
    } catch {
      setErrors(['Adding text failed. Please try again.']);
    } finally {
      finishUpload();
    }
  };

  const handleUploadFiles = async () => {
    if (isUploading || uploadInFlightRef.current) return;

    if (files.length === 0 && !urlInput) {
      setErrors(['Please select files or enter a URL']);
      return;
    }

    if (!startUpload()) return;

    try {
      if (uploadType === 'file' && files.length > 0) {
        await onUpload(files);
        setFiles([]);
      } else if ((uploadType === 'url' || uploadType === 'youtube') && urlInput) {
        await onUpload([urlInput]);
        setUrlInput('');
      }
      setErrors([]);
    } catch {
      setErrors(['Upload failed. Please try again.']);
    } finally {
      finishUpload();
    }
  };

  const getFileIcon = (fileName: string) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (ext === 'pptx') return <Presentation className="w-4 h-4" />;
    if (ext === 'xlsx') return <FileSpreadsheet className="w-4 h-4" />;
    if (ext === 'epub') return <BookOpen className="w-4 h-4" />;
    if (['pdf', 'txt', 'md', 'docx'].includes(ext || '')) {
      return <FileText className="w-4 h-4" />;
    }
    return <File className="w-4 h-4" />;
  };

  return (
    <div className="w-full p-4">
      {/* Upload Type Selector — a segmented control: the chosen kind is the
          white pill on the muted track, so it reads at a glance. */}
      <div className="inline-flex flex-wrap gap-1 mb-4 p-1 rounded-lg bg-[var(--muted)]">
        <button
          onClick={() => setUploadType('file')}
          aria-pressed={uploadType === 'file'}
          className={`h-8 px-3 text-sm rounded-md transition-colors ${
            uploadType === 'file'
              ? 'bg-[var(--card)] text-[var(--foreground)] font-medium ring-1 ring-[var(--border)]'
              : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
          }`}
        >
          <File className="inline w-4 h-4 mr-1.5 -mt-0.5" />
          File
        </button>
        <button
          onClick={() => setUploadType('url')}
          aria-pressed={uploadType === 'url'}
          className={`h-8 px-3 text-sm rounded-md transition-colors ${
            uploadType === 'url'
              ? 'bg-[var(--card)] text-[var(--foreground)] font-medium ring-1 ring-[var(--border)]'
              : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
          }`}
        >
          <Link className="inline w-4 h-4 mr-1.5 -mt-0.5" />
          URL
        </button>
        <button
          onClick={() => setUploadType('youtube')}
          aria-pressed={uploadType === 'youtube'}
          className={`h-8 px-3 text-sm rounded-md transition-colors ${
            uploadType === 'youtube'
              ? 'bg-[var(--card)] text-[var(--foreground)] font-medium ring-1 ring-[var(--border)]'
              : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
          }`}
        >
          <Youtube className="inline w-4 h-4 mr-1.5 -mt-0.5" />
          YouTube
        </button>
        {onAddText && (
          <button
            onClick={() => setUploadType('text')}
            aria-pressed={uploadType === 'text'}
            className={`h-8 px-3 text-sm rounded-md transition-colors ${
              uploadType === 'text'
                ? 'bg-[var(--card)] text-[var(--foreground)] font-medium ring-1 ring-[var(--border)]'
                : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
            }`}
          >
            <FileText className="inline w-4 h-4 mr-1.5 -mt-0.5" />
            Text
          </button>
        )}
      </div>

      {/* Pasted Text Area */}
      {uploadType === 'text' && (
        <div className="border border-[var(--input)] rounded-lg p-4 space-y-2">
          <input
            type="text"
            aria-label="Source title"
            value={textTitle}
            onChange={(e) => setTextTitle(e.target.value)}
            placeholder="Title"
            maxLength={200}
            className="w-full px-3 py-2 border border-[var(--input)] rounded-lg focus:outline-none focus:border-[var(--ring)]"
          />
          <textarea
            aria-label="Source text"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            placeholder="Paste text here..."
            rows={8}
            className="w-full px-3 py-2 border border-[var(--input)] rounded-lg focus:outline-none focus:border-[var(--ring)]"
          />
          <button
            onClick={() => void handleTextSubmit()}
            disabled={!textTitle.trim() || !textInput.trim() || isUploading}
            className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Add text
          </button>
        </div>
      )}

      {/* File Upload Area */}
      {uploadType === 'file' && (
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            isDragging
              ? 'border-[var(--ring)] bg-[var(--muted)]'
              : 'border-[var(--input)] hover:border-[var(--muted-foreground)]'
          }`}
        >
          <Upload className="w-12 h-12 mx-auto mb-4 text-[var(--muted-foreground)]" />
          <p className="text-[var(--muted-foreground)] mb-2">
            Drag and drop files here, or{' '}
            <label className="text-[var(--foreground)] hover:text-[var(--foreground)] cursor-pointer">
              browse
              <input
                type="file"
                className="hidden"
                accept={accept}
                multiple={multiple}
                onChange={handleFileInput}
              />
            </label>
          </p>
          <p className="text-sm text-[var(--muted-foreground)]">
            PDF, TXT, Markdown, Word, PowerPoint, Excel, EPUB, images, or audio · Maximum file size: {maxSize}MB
          </p>
        </div>
      )}

      {/* URL Input Area */}
      {(uploadType === 'url' || uploadType === 'youtube') && (
        <div className="border border-[var(--input)] rounded-lg p-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder={
                uploadType === 'youtube'
                  ? 'Enter YouTube URL...'
                  : 'Enter website URL...'
              }
              className="flex-1 px-3 py-2 border border-[var(--input)] rounded-lg focus:outline-none focus:border-[var(--ring)]"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleUrlSubmit();
                }
              }}
            />
            <button
              onClick={() => void handleUrlSubmit()}
              disabled={!urlInput.trim() || isUploading}
              className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Add
            </button>
          </div>
        </div>
      )}

      {/* Error Messages */}
      {errors.length > 0 && (
        <div className="mt-4 p-3 bg-[var(--error-bg)] border border-[var(--error)] rounded-lg">
          {errors.map((error, index) => (
            <p key={index} className="text-sm text-[var(--error)]">
              {error}
            </p>
          ))}
        </div>
      )}

      {/* File List */}
      {files.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-sm font-medium text-[var(--muted-foreground)]">Selected Files:</h4>
          {files.map((file, index) => (
            <div
              key={index}
              className="flex items-center justify-between p-3 bg-[var(--muted)] rounded-lg"
            >
              <div className="flex items-center gap-2">
                {getFileIcon(file.name)}
                <span className="text-sm text-[var(--muted-foreground)]">{file.name}</span>
                <span className="text-xs text-[var(--muted-foreground)]">
                  ({(file.size / 1024 / 1024).toFixed(2)} MB)
                </span>
              </div>
              <button
                onClick={() => removeFile(index)}
                aria-label={'Remove file'}
                title={'Remove file'}
                className="text-[var(--muted-foreground)] hover:text-[var(--error)]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Upload Button */}
      {(files.length > 0 || (urlInput && (uploadType === 'url' || uploadType === 'youtube'))) && (
        <button
          onClick={handleUploadFiles}
          disabled={isUploading}
          className="mt-4 w-full px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isUploading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Uploading...
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              Upload {uploadType === 'file' ? `${files.length} file(s)` : 'URL'}
            </>
          )}
        </button>
      )}
    </div>
  );
}
