'use client';

import React, { useId } from 'react';

interface BrandLogoProps extends React.SVGProps<SVGSVGElement> {
  label?: string;
}

/**
 * The product mark: one node holding five sources, where each edge's weight is
 * how much that source carries. It is drawn rather than fetched — the mark it
 * replaces arrived as a 97 KB PNG behind an `<image href>`, which cost a
 * request in all five places this renders and could not follow the theme.
 *
 * There is deliberately no tile behind it. The marks paint from `--primary`
 * and `--accent` themselves, so one drawing sits on the nav, the login page
 * and a chat bubble without a hard-coded light card propping it up in dark
 * mode.
 */
export default function BrandLogo({ label, ...props }: BrandLogoProps) {
  // Several marks share a page — the chat welcome, the streaming row, the nav —
  // and a duplicated gradient id would leave every mark but the first
  // unpainted. useId's output carries punctuation an SVG id has no business
  // holding, so strip it.
  const gradientId = `brand-mark-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const paint = `url(#${gradientId})`;

  return (
    <svg
      {...props}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-brand-logo="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id={gradientId}
          x1="0"
          y1="0"
          x2="24"
          y2="24"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--accent)" />
        </linearGradient>
      </defs>

      {/* Edge weight is citation weight, so the two sources carrying the answer
          read first at any size and the lightest is the first thing to go when
          the mark is set small. */}
      <g stroke={paint} fill="none" strokeLinecap="round">
        <path d="M12 12 4.5 9.3" strokeWidth="2.2" />
        <path d="M12 12 9.3 4.5" strokeWidth="1.1" />
        <path d="M12 12 18.1 6.9" strokeWidth="1.6" />
        <path d="M12 12 19.5 14.7" strokeWidth="2.6" />
        <path d="M12 12 9.9 19.7" strokeWidth="0.9" />
      </g>

      {/* Nowhere near the clock positions, on purpose: evenly spaced nodes read
          as a loading spinner. Drawn after the edges, and well over twice the
          edge width, so each node stays a node instead of collapsing into the
          line that reaches it. */}
      <g fill={paint}>
        <circle cx="12" cy="12" r="3.4" />
        <circle cx="4.5" cy="9.3" r="1.7" />
        <circle cx="9.3" cy="4.5" r="1.15" />
        <circle cx="18.1" cy="6.9" r="1.4" />
        <circle cx="19.5" cy="14.7" r="1.9" />
        <circle cx="9.9" cy="19.7" r="1" />
      </g>
    </svg>
  );
}
