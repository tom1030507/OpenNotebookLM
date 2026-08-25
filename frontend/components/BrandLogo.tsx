'use client';

import React from 'react';

interface BrandLogoProps extends React.SVGProps<SVGSVGElement> {
  label?: string;
}

export default function BrandLogo({ label, ...props }: BrandLogoProps) {
  return (
    <svg
      {...props}
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-brand-logo="true"
      focusable="false"
    >
      <rect
        x="1"
        y="1"
        width="62"
        height="62"
        rx="13"
        fill="#F8FAFC"
        stroke="#E2E8F0"
        strokeWidth="1"
      />
      <image
        href="/brand-logo-f.png"
        width="64"
        height="64"
        preserveAspectRatio="xMidYMid meet"
      />
    </svg>
  );
}
