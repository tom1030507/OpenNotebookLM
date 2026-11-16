'use client';

import React from 'react';
import { Toaster } from 'react-hot-toast';


// Below the 56px top bar: placed over it, a toast covered the toolbar icons
// and swallowed clicks on the notification bell for as long as it showed.
const TOP_BAR_CLEARANCE_PX = 64;

export default function NotificationProvider() {
  return (
    <Toaster
      position="top-right"
      containerStyle={{ top: TOP_BAR_CLEARANCE_PX }}
      toastOptions={{
        duration: 5000,
        // Theme tokens rather than the library's fixed white: a transparent
        // toast showed dark grey text straight on the dark page (#228).
        style: {
          background: 'var(--popover)',
          color: 'var(--card-foreground)',
          border: '1px solid var(--border)',
          boxShadow: '0 8px 24px rgb(0 0 0 / 0.12)',
          fontSize: '0.875rem',
        },
      }}
    />
  );
}
