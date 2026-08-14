import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { AUTH_TOKEN_COOKIE } from './lib/session';

// Public routes that don't require authentication
const publicRoutes = ['/login', '/register'];

const isPublicRoute = (pathname: string) => publicRoutes.some(
  (route) => pathname === route || pathname.startsWith(`${route}/`),
);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicRoute(pathname)) {
    return NextResponse.next();
  }

  // The workspace keeps its token in localStorage, which middleware cannot
  // read, so sign-in mirrors it into this cookie and sign-out expires it
  // (see lib/session.ts).
  if (!request.cookies.get(AUTH_TOKEN_COOKIE)) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  return NextResponse.next();
}

// Configure which routes to run middleware on
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public files
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\..*|api/health).*)',
  ],
};
