import { afterEach, describe, expect, test, vi } from 'vitest';


afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});


describe('browser API routing', () => {
  test('uses the frontend origin instead of exposing a backend host', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://backend:8000/api');

    const { API_BASE_URL, apiUrl } = await import('./api');

    expect(API_BASE_URL).toBe('/api');
    expect(apiUrl('/projects')).toBe('/api/projects');
  });

  test('proxies API requests to the configured internal backend', async () => {
    vi.stubEnv('BACKEND_INTERNAL_URL', 'http://internal-backend:9000/');

    const { default: nextConfig } = await import('../next.config');
    expect(nextConfig.rewrites).toBeTypeOf('function');

    const rewrites = await nextConfig.rewrites!();

    expect(rewrites).toContainEqual({
      source: '/api/:path*',
      destination: 'http://internal-backend:9000/api/:path*',
    });
  });
});
