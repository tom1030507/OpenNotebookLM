'use client';

import React, { useEffect } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { Bell, CheckCircle, AlertCircle, Info, X } from 'lucide-react';
import wsService from '@/lib/websocket';

export default function NotificationProvider() {
  useEffect(() => {
    // Listen for WebSocket notifications
    const handleNotification = (data: any) => {
      switch (data.type) {
        case 'success':
          toast.custom((t) => (
            <div className={`${
              t.visible ? 'animate-enter' : 'animate-leave'
            } max-w-md w-full bg-white dark:bg-gray-800 shadow-lg rounded-lg pointer-events-auto flex ring-1 ring-black ring-opacity-5`}>
              <div className="flex-1 w-0 p-4">
                <div className="flex items-start">
                  <div className="flex-shrink-0">
                    <CheckCircle className="h-5 w-5 text-green-500" />
                  </div>
                  <div className="ml-3 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {data.title || 'Success'}
                    </p>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      {data.message}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex border-l border-gray-200 dark:border-gray-700">
                <button
                  onClick={() => toast.dismiss(t.id)}
                  className="w-full border border-transparent rounded-none rounded-r-lg p-4 flex items-center justify-center text-sm font-medium text-indigo-600 hover:text-indigo-500 focus:outline-none"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ));
          break;
        
        case 'error':
          toast.custom((t) => (
            <div className={`${
              t.visible ? 'animate-enter' : 'animate-leave'
            } max-w-md w-full bg-white dark:bg-gray-800 shadow-lg rounded-lg pointer-events-auto flex ring-1 ring-black ring-opacity-5`}>
              <div className="flex-1 w-0 p-4">
                <div className="flex items-start">
                  <div className="flex-shrink-0">
                    <AlertCircle className="h-5 w-5 text-red-500" />
                  </div>
                  <div className="ml-3 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {data.title || 'Error'}
                    </p>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      {data.message}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex border-l border-gray-200 dark:border-gray-700">
                <button
                  onClick={() => toast.dismiss(t.id)}
                  className="w-full border border-transparent rounded-none rounded-r-lg p-4 flex items-center justify-center text-sm font-medium text-red-600 hover:text-red-500 focus:outline-none"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ));
          break;
        
        case 'info':
        default:
          toast.custom((t) => (
            <div className={`${
              t.visible ? 'animate-enter' : 'animate-leave'
            } max-w-md w-full bg-white dark:bg-gray-800 shadow-lg rounded-lg pointer-events-auto flex ring-1 ring-black ring-opacity-5`}>
              <div className="flex-1 w-0 p-4">
                <div className="flex items-start">
                  <div className="flex-shrink-0">
                    <Info className="h-5 w-5 text-blue-500" />
                  </div>
                  <div className="ml-3 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {data.title || 'Notification'}
                    </p>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      {data.message}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex border-l border-gray-200 dark:border-gray-700">
                <button
                  onClick={() => toast.dismiss(t.id)}
                  className="w-full border border-transparent rounded-none rounded-r-lg p-4 flex items-center justify-center text-sm font-medium text-blue-600 hover:text-blue-500 focus:outline-none"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ));
          break;
      }
    };

    const handleProcessingStatus = (data: any) => {
      if (data.status === 'completed') {
        toast.success(`Document "${data.document_name}" processed successfully!`);
      } else if (data.status === 'failed') {
        toast.error(`Failed to process document "${data.document_name}"`);
      }
    };

    wsService.on('notification', handleNotification);
    wsService.on('processing:status', handleProcessingStatus);

    return () => {
      wsService.off('notification', handleNotification);
      wsService.off('processing:status', handleProcessingStatus);
    };
  }, []);

  return (
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 5000,
        style: {
          background: 'transparent',
          boxShadow: 'none',
        },
      }}
    />
  );
}
