'use client';

import React from 'react';
import { Toaster } from 'react-hot-toast';


export default function NotificationProvider() {
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
