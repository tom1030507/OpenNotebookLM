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

/** The keys `storeSession` mirrors the access token into. */
const TOKEN_KEYS = ['access_token', 'auth_token'] as const;

const STORAGE_KEYS = [...TOKEN_KEYS, 'user'] as const;

// A token is normally unique, but account transitions must also retire a
// request if a replacement session happens to reuse its credential.
let sessionGeneration = 0;

export interface SessionUser {
  username: string;
  email: string;
}

export interface SessionCredentialSnapshot {
  authorization: string | null;
  generation: number;
}

/**
 * Match cookie names exactly rather than accepting a similarly named cookie.
 * The middleware can authenticate a cookie-only browser session even when
 * localStorage is denied, so that cookie is a session credential too.
 */
const hasCookie = (name: string): boolean => {
  if (typeof document === 'undefined') {
    return false;
  }

  return document.cookie.split(';').some((entry) => {
    const trimmed = entry.trim();
    const separator = trimmed.indexOf('=');
    const cookieName = separator === -1 ? trimmed : trimmed.slice(0, separator);
    return cookieName === name;
  });
};

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


const isStoredSessionUser = (value: unknown): value is SessionUser => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }

  const user = value as Record<string, unknown>;
  return typeof user.username === 'string'
    && user.username.trim().length > 0
    && typeof user.email === 'string';
};

/** Record a signed-in session for both the client and the middleware. */
export const storeSession = (
  accessToken: string,
  user: SessionUser,
  clearAccountState?: () => void,
): void => {
  sessionGeneration += 1;
  let previousUser: SessionUser | null = null;
  let mustClearAccountState = false;

  try {
    const storedUser = window.localStorage.getItem('user');
    if (storedUser !== null) {
      try {
        const parsedUser: unknown = JSON.parse(storedUser);
        if (isStoredSessionUser(parsedUser)) {
          previousUser = parsedUser;
        } else {
          mustClearAccountState = true;
        }
      } catch {
        mustClearAccountState = true;
      }
    }
  } catch {
    mustClearAccountState = true;
  }

  // An unreadable or invalid identity makes the current workspace untrustworthy.
  // Clear it before replacement writes, which remain independent so the user
  // can still sign in when old storage is malformed or unavailable.
  const accountChanged = previousUser !== null && previousUser.username !== user.username;
  if (mustClearAccountState || accountChanged) {
    clearAccountState?.();
  }

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

/**
 * Read the access token the API client has to send.
 *
 * `storeSession` writes the same value under both keys, so either one is the
 * session: a browsing context that kept only one of them still works. Returns
 * null on the server, where there is no storage to read.
 */
export const readAccessToken = (): string | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  for (const key of TOKEN_KEYS) {
    try {
      const token = window.localStorage.getItem(key);
      if (token) {
        return token;
      }
    } catch {
      // Storage can be denied outright, which reads as signed out.
      return null;
    }
  }

  return null;
};

/** Capture the exact Authorization value sent with a request. */
export const snapshotSessionCredential = (
  authorization: string | null,
): SessionCredentialSnapshot => ({
  authorization,
  generation: sessionGeneration,
});

/** True only while the request still belongs to the active browser session. */
export const isCurrentSessionCredential = (
  snapshot: SessionCredentialSnapshot,
): boolean => {
  if (snapshot.generation !== sessionGeneration) {
    return false;
  }

  const currentToken = readAccessToken();
  if (snapshot.authorization === null) {
    return currentToken === null && hasCookie(AUTH_TOKEN_COOKIE);
  }

  return currentToken !== null && snapshot.authorization === `Bearer ${currentToken}`;
};

/** Forget the signed-in session. */
export const clearSession = (): void => {
  sessionGeneration += 1;
  for (const key of STORAGE_KEYS) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Expiring the cookie below is what actually locks the workspace.
    }
  }

  writeCookie('', 0);
};
