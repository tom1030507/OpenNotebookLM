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
      <image
        href="/brand-logo-f.png"
        width="64"
        height="64"
        preserveAspectRatio="xMidYMid meet"
      />
    </svg>
  );
}
