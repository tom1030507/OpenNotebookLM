/**
 * Browser-side session storage.
 *
 * The workspace reads its token from localStorage, but `middleware.ts` runs on
 * the server and can only see cookies. Sign-in therefore writes both, and
 * sign-out clears both, so the two never disagree about who is signed in.
 */

export const AUTH_TOKEN_COOKIE = 'auth_token';

/** Matches the backend's default ACCESS_TOKEN_EXPIRE_MINUTES of 720. */
const SESSION_MAX_AGE_SECONDS = 12 * 60 * 60;

const STORAGE_KEYS = ['access_token', 'auth_token', 'user'] as const;

export interface SessionUser {
  username: string;
  email: string;
}

const writeCookie = (value: string, maxAgeSeconds: number) => {
  const attributes = [
    `${AUTH_TOKEN_COOKIE}=${encodeURIComponent(value)}`,
    'Path=/',
    'SameSite=Lax',
    `Max-Age=${maxAgeSeconds}`,
  ];

  // Localhost development is served over plain HTTP, where a Secure cookie
  // would simply be dropped.
  if (window.location.protocol === 'https:') {
    attributes.push('Secure');
  }

  document.cookie = attributes.join('; ');
};

/** Record a signed-in session for both the client and the middleware. */
export const storeSession = (accessToken: string, user: SessionUser): void => {
  try {
    window.localStorage.setItem('access_token', accessToken);
    // The API client and TopNav both read this key.
    window.localStorage.setItem('auth_token', accessToken);
    window.localStorage.setItem('user', JSON.stringify(user));
  } catch {
    // The cookie below still carries the session for this browsing context.
  }

  writeCookie(accessToken, SESSION_MAX_AGE_SECONDS);
};

/** Forget the signed-in session. */
export const clearSession = (): void => {
  for (const key of STORAGE_KEYS) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Expiring the cookie below is what actually locks the workspace.
    }
  }

  writeCookie('', 0);
};
