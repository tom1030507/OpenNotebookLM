'use client';

import React, { useId } from 'react';

interface BrandLogoProps extends React.SVGProps<SVGSVGElement> {
  label?: string;
}

export default function BrandLogo({ label, ...props }: BrandLogoProps) {
  const maskId = `brand-logo-${useId().replace(/:/g, '')}`;

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
      <defs>
        <mask id={maskId}>
          <rect width="64" height="64" fill="white" />
          <path
            d="M32 18c1.5 6.5 6.5 11.5 13 13-6.5 1.5-11.5 6.5-13 13-1.5-6.5-6.5-11.5-13-13 6.5-1.5 11.5-6.5 13-13Z"
            fill="black"
          />
        </mask>
      </defs>
      <g mask={`url(#${maskId})`}>
        <rect
          data-brand-layer="primary"
          x="4"
          y="4"
          width="38"
          height="38"
          rx="10"
          fill="#155EEF"
        />
        <rect
          data-brand-layer="secondary"
          x="22"
          y="22"
          width="38"
          height="38"
          rx="10"
          fill="#1F2937"
        />
      </g>
    </svg>
  );
}
