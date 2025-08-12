'use client';

import React from 'react';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'rectangular' | 'circular';
  animation?: 'pulse' | 'wave' | 'none';
  width?: string | number;
  height?: string | number;
}

export function Skeleton({
  className = '',
  variant = 'text',
  animation = 'pulse',
  width,
  height,
}: SkeletonProps) {
  const baseClasses = 'bg-gray-200 dark:bg-gray-700';
  
  const variantClasses = {
    text: 'rounded',
    rectangular: 'rounded-lg',
    circular: 'rounded-full',
  };
  
  const animationClasses = {
    pulse: 'animate-pulse',
    wave: 'animate-shimmer',
    none: '',
  };
  
  const style: React.CSSProperties = {
    width: width || (variant === 'circular' ? 40 : '100%'),
    height: height || (variant === 'text' ? 20 : variant === 'circular' ? 40 : 100),
  };
  
  return (
    <div
      className={`${baseClasses} ${variantClasses[variant]} ${animationClasses[animation]} ${className}`}
      style={style}
    />
  );
}

export function DocumentSkeleton() {
  return (
    <div className="p-3 bg-[var(--card)] rounded-lg border border-[var(--border)]">
      <div className="flex items-start gap-3">
        <Skeleton variant="rectangular" width={32} height={32} className="rounded" />
        <div className="flex-1">
          <Skeleton variant="text" height={16} className="mb-2" />
          <Skeleton variant="text" width="60%" height={12} />
        </div>
      </div>
    </div>
  );
}

export function ConversationSkeleton() {
  return (
    <div className="p-3 rounded-lg">
      <div className="flex items-start gap-2">
        <Skeleton variant="circular" width={16} height={16} className="mt-0.5" />
        <div className="flex-1">
          <Skeleton variant="text" height={14} className="mb-1" />
          <Skeleton variant="text" width="40%" height={12} />
        </div>
      </div>
    </div>
  );
}

export function MessageSkeleton() {
  return (
    <div className="flex gap-3">
      <Skeleton variant="circular" width={32} height={32} />
      <div className="flex-1 max-w-[70%]">
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg px-4 py-3">
          <Skeleton variant="text" className="mb-2" />
          <Skeleton variant="text" className="mb-2" />
          <Skeleton variant="text" width="80%" />
        </div>
      </div>
    </div>
  );
}

export function ChatAreaSkeleton() {
  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--background)]">
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          <MessageSkeleton />
          <div className="flex gap-3 justify-end">
            <div className="max-w-[70%]">
              <div className="bg-[var(--primary)] bg-opacity-10 rounded-lg px-4 py-3">
                <Skeleton variant="text" className="bg-[var(--primary)] bg-opacity-20" />
              </div>
            </div>
            <Skeleton variant="circular" width={32} height={32} />
          </div>
          <MessageSkeleton />
        </div>
      </div>
      <div className="border-t border-[var(--border)] bg-[var(--card)] p-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3">
            <Skeleton variant="rectangular" width={40} height={40} className="rounded-lg" />
            <Skeleton variant="rectangular" className="flex-1" height={48} />
            <Skeleton variant="rectangular" width={48} height={48} className="rounded-lg" />
          </div>
        </div>
      </div>
    </div>
  );
}
