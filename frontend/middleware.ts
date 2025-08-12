import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Public routes that don't require authentication
const publicRoutes = ['/login', '/register', '/api/auth'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // For development, we'll be more permissive
  // Only redirect to login if accessing root without any auth
  if (pathname === '/' || pathname === '') {
    // Check for any form of authentication
    const cookieToken = request.cookies.get('auth_token');
    const authHeader = request.headers.get('authorization');
    
    // If no auth at all, redirect to login
    if (!cookieToken && !authHeader) {
      return NextResponse.redirect(new URL('/login', request.url));
    }
  }

  // Allow all other requests to proceed
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
