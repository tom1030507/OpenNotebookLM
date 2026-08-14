// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest';

import { AUTH_TOKEN_COOKIE, clearSession, storeSession } from './session';


const cookieValue = (name: string) => document.cookie
  .split('; ')
  .find((entry) => entry.startsWith(`${name}=`))
  ?.slice(name.length + 1);


beforeEach(() => {
  window.localStorage.clear();
  clearSession();
});


describe('browser session', () => {
  it('mirrors the token into a cookie so middleware can see it', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe('a-signed-token');
  });

  it('keeps the token in localStorage for the API client', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    expect(window.localStorage.getItem('access_token')).toBe('a-signed-token');
    expect(window.localStorage.getItem('auth_token')).toBe('a-signed-token');
    expect(JSON.parse(window.localStorage.getItem('user') as string)).toEqual({
      username: 'ada',
      email: 'ada@example.com',
    });
  });

  it('clears the cookie and the stored account on sign-out', () => {
    storeSession('a-signed-token', { username: 'ada', email: 'ada@example.com' });

    clearSession();

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBeUndefined();
    expect(window.localStorage.getItem('access_token')).toBeNull();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(window.localStorage.getItem('user')).toBeNull();
  });

  it('escapes a token that would otherwise break the cookie header', () => {
    storeSession('token with; semicolon', { username: 'ada', email: 'ada@example.com' });

    expect(cookieValue(AUTH_TOKEN_COOKIE)).toBe(
      encodeURIComponent('token with; semicolon'),
    );
  });
});
