import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { middleware } from './middleware';
import { AUTH_TOKEN_COOKIE } from './lib/session';


const requestFor = (path: string, cookie?: string) => new NextRequest(
  new URL(path, 'http://localhost:3000'),
  cookie ? { headers: { cookie } } : undefined,
);


describe('route protection middleware', () => {
  it.each([
    '/api',
    '/api/auth/token',
    '/api/projects',
  ])('lets the backend own authentication for signed-out API route %s', (path) => {
    const response = middleware(requestFor(path));

    expect(response.status).toBe(200);
    expect(response.headers.get('location')).toBeNull();
  });

  it('sends a signed-out visitor from the workspace to the login page', () => {
    const response = middleware(requestFor('/'));

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://localhost:3000/login');
  });

  it('lets a signed-in visitor reach the workspace', () => {
    const response = middleware(
      requestFor('/', `${AUTH_TOKEN_COOKIE}=a-signed-token`),
    );

    expect(response.headers.get('location')).toBeNull();
    expect(response.status).toBe(200);
  });

  it('leaves the login page reachable while signed out', () => {
    const response = middleware(requestFor('/login'));

    expect(response.headers.get('location')).toBeNull();
  });

  it('protects other workspace routes as well', () => {
    const response = middleware(requestFor('/projects/project-1'));

    expect(response.headers.get('location')).toBe('http://localhost:3000/login');
  });
});
