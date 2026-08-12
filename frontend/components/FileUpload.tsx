'use client';

import React, { useState, useCallback } from 'react';
import { Upload, X, File, Link, Youtube, FileText, Loader2 } from 'lucide-react';
import { getUploadFileError } from '@/lib/uploadValidation';
import { uiCopy } from '@/lib/uiCopy';

interface FileUploadProps {
  onUpload: (files: File[] | string[]) => Promise<void>;
  accept?: string;
  multiple?: boolean;
  maxSize?: number; // in MB
}

type UploadType = 'file' | 'url' | 'youtube';

interface FileUploadUrlFieldsProps {
  uploadType: Extract<UploadType, 'url' | 'youtube'>;
  urlInput: string;
  isUploading: boolean;
  onUrlChange: (value: string) => void;
  onSubmit: () => void;
}

export function FileUploadUrlFields({
  uploadType,
  urlInput,
  isUploading,
  onUrlChange,
  onSubmit,
}: FileUploadUrlFieldsProps) {
  return (
    <div className="border border-gray-300 rounded-lg p-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={urlInput}
          onChange={(event) => onUrlChange(event.target.value)}
          placeholder={
            uploadType === 'youtube'
              ? uiCopy.upload.youtubeUrlPlaceholder
              : uiCopy.upload.urlPlaceholder
          }
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-purple-500"
          onKeyPress={(event) => {
            if (event.key === 'Enter') {
              onSubmit();
            }
          }}
        />
        <button
          onClick={onSubmit}
          disabled={!urlInput.trim() || isUploading}
          className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {uiCopy.upload.add}
        </button>
      </div>
    </div>
  );
}

interface FileUploadErrorsProps {
  errors: string[];
}

export function FileUploadErrors({ errors }: FileUploadErrorsProps) {
  if (errors.length === 0) return null;

  return (
    <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
      {errors.map((error, index) => (
        <p key={index} className="text-sm text-red-600">
          {error}
        </p>
      ))}
    </div>
  );
}

export default function FileUpload({ 
  onUpload, 
  accept = '.pdf',
  multiple = false,
  maxSize = 10 
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [urlInput, setUrlInput] = useState('');
  const [uploadType, setUploadType] = useState<UploadType>('file');
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
    if (!urlInput.trim()) {
      setErrors([uiCopy.upload.validUrl]);
      return;
    }

    try {
      new URL(urlInput);
    } catch {
      setErrors([uiCopy.upload.validUrl]);
      return;
    }

    try {
      setIsUploading(true);
      await onUpload([urlInput]);
      setUrlInput('');
      setErrors([]);
    } catch {
      setErrors([uiCopy.upload.uploadUrlFailed]);
    } finally {
      setIsUploading(false);
    }
  };

  const handleUploadFiles = async () => {
    if (files.length === 0 && !urlInput) {
      setErrors([uiCopy.upload.selectFilesOrUrl]);
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
    } catch {
      setErrors([uiCopy.upload.uploadFailed]);
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
          {uiCopy.upload.file}
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
            {uiCopy.upload.dragAndDrop}{' '}
            <label className="text-purple-600 hover:text-purple-700 cursor-pointer">
              {uiCopy.upload.browse}
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
            {uiCopy.upload.maxFileSize}{maxSize}MB
          </p>
        </div>
      )}

      {/* URL Input Area */}
      {(uploadType === 'url' || uploadType === 'youtube') && (
        <FileUploadUrlFields
          uploadType={uploadType}
          urlInput={urlInput}
          isUploading={isUploading}
          onUrlChange={setUrlInput}
          onSubmit={() => void handleUrlSubmit()}
        />
      )}

      {/* Error Messages */}
      <FileUploadErrors errors={errors} />

      {/* File List */}
      {files.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-sm font-medium text-gray-700">{uiCopy.upload.selectedFiles}</h4>
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
              {uiCopy.upload.uploading}
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              {uiCopy.upload.upload} {uploadType === 'file' ? `${files.length} 個檔案` : 'URL'}
            </>
          )}
        </button>
      )}
    </div>
  );
}
