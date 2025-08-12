import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Public routes that don't require authentication
const publicRoutes = ['/login', '/register', '/api/auth'];

export function middleware(request: NextRequest) {
  // DISABLED - Allow all requests without authentication
  return NextResponse.next();
  
  // Original authentication logic commented out for development
  /*
  const { pathname } = request.nextUrl;
  if (pathname === '/' || pathname === '') {
    const cookieToken = request.cookies.get('auth_token');
    const authHeader = request.headers.get('authorization');
    if (!cookieToken && !authHeader) {
      return NextResponse.redirect(new URL('/login', request.url));
    }
  }
  return NextResponse.next();
  */
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
