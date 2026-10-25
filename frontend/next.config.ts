import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    middlewareClientMaxBodySize: `${Number(process.env.MAX_FILE_SIZE_MB || 50) + 2}mb`,
  },
  // The dev-only badge sits over the sidebar's bottom-left corner, on top of the
  // Conversations toggle and the last conversation row, and swallows clicks there.
  devIndicators: false,
  async rewrites() {
    const backendUrl = (
      process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000'
    ).replace(/\/+$/, '');

    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
