import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
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
