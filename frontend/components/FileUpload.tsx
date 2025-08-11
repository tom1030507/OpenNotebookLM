'use client';

import React, { useState, useCallback } from 'react';
import { Upload, X, File, Link, Youtube, FileText, Loader2 } from 'lucide-react';

interface FileUploadProps {
  onUpload: (files: File[] | string[]) => void;
  accept?: string;
  multiple?: boolean;
  maxSize?: number; // in MB
}

export default function FileUpload({ 
  onUpload, 
  accept = '.pdf,.txt,.doc,.docx', 
  multiple = true,
  maxSize = 10 
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [urlInput, setUrlInput] = useState('');
  const [uploadType, setUploadType] = useState<'file' | 'url' | 'youtube'>('file');
  const [errors, setErrors] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    const droppedFiles = Array.from(e.dataTransfer.files);
    validateAndAddFiles(droppedFiles);
  }, []);

  const validateAndAddFiles = (newFiles: File[]) => {
    const errors: string[] = [];
    const validFiles: File[] = [];

    newFiles.forEach(file => {
      // Check file size
      if (file.size > maxSize * 1024 * 1024) {
        errors.push(`${file.name} exceeds ${maxSize}MB limit`);
        return;
      }

      // Check if file already exists
      if (files.some(f => f.name === file.name)) {
        errors.push(`${file.name} already added`);
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

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files);
      validateAndAddFiles(selectedFiles);
    }
  };

  const removeFile = (index: number) => {
    setFiles(files.filter((_, i) => i !== index));
  };

  const handleUrlSubmit = () => {
    if (!urlInput.trim()) {
      setErrors(['Please enter a valid URL']);
      return;
    }

    // Basic URL validation
    try {
      new URL(urlInput);
      onUpload([urlInput]);
      setUrlInput('');
      setErrors([]);
    } catch {
      setErrors(['Please enter a valid URL']);
    }
  };

  const handleUploadFiles = async () => {
    if (files.length === 0 && !urlInput) {
      setErrors(['Please select files or enter a URL']);
      return;
    }

    setIsUploading(true);
    try {
      if (uploadType === 'file' && files.length > 0) {
        await onUpload(files);
        setFiles([]);
      } else if ((uploadType === 'url' || uploadType === 'youtube') && urlInput) {
        await onUpload([urlInput]);
        setUrlInput('');
      }
      setErrors([]);
    } catch (error) {
      setErrors(['Upload failed. Please try again.']);
    } finally {
      setIsUploading(false);
    }
  };

  const getFileIcon = (fileName: string) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return <FileText className="w-4 h-4" />;
    return <File className="w-4 h-4" />;
  };

  return (
    <div className="w-full p-4">
      {/* Upload Type Selector */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setUploadType('file')}
          className={`px-4 py-2 rounded-lg transition-colors ${
            uploadType === 'file'
              ? 'bg-purple-100 text-purple-700'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <File className="inline w-4 h-4 mr-2" />
          File
        </button>
        <button
          onClick={() => setUploadType('url')}
          className={`px-4 py-2 rounded-lg transition-colors ${
            uploadType === 'url'
              ? 'bg-purple-100 text-purple-700'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <Link className="inline w-4 h-4 mr-2" />
          URL
        </button>
        <button
          onClick={() => setUploadType('youtube')}
          className={`px-4 py-2 rounded-lg transition-colors ${
            uploadType === 'youtube'
              ? 'bg-purple-100 text-purple-700'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <Youtube className="inline w-4 h-4 mr-2" />
          YouTube
        </button>
      </div>

      {/* File Upload Area */}
      {uploadType === 'file' && (
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            isDragging
              ? 'border-purple-500 bg-purple-50'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          <Upload className="w-12 h-12 mx-auto mb-4 text-gray-400" />
          <p className="text-gray-600 mb-2">
            Drag and drop files here, or{' '}
            <label className="text-purple-600 hover:text-purple-700 cursor-pointer">
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
          <p className="text-sm text-gray-500">
            Maximum file size: {maxSize}MB
          </p>
        </div>
      )}

      {/* URL Input Area */}
      {(uploadType === 'url' || uploadType === 'youtube') && (
        <div className="border border-gray-300 rounded-lg p-4">
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
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-purple-500"
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleUrlSubmit();
                }
              }}
            />
            <button
              onClick={handleUrlSubmit}
              disabled={!urlInput.trim()}
              className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              Add
            </button>
          </div>
        </div>
      )}

      {/* Error Messages */}
      {errors.length > 0 && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          {errors.map((error, index) => (
            <p key={index} className="text-sm text-red-600">
              {error}
            </p>
          ))}
        </div>
      )}

      {/* File List */}
      {files.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-sm font-medium text-gray-700">Selected Files:</h4>
          {files.map((file, index) => (
            <div
              key={index}
              className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
            >
              <div className="flex items-center gap-2">
                {getFileIcon(file.name)}
                <span className="text-sm text-gray-700">{file.name}</span>
                <span className="text-xs text-gray-500">
                  ({(file.size / 1024 / 1024).toFixed(2)} MB)
                </span>
              </div>
              <button
                onClick={() => removeFile(index)}
                className="text-gray-400 hover:text-red-500"
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
          className="mt-4 w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center gap-2"
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
