'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { 
  LogIn, 
  UserPlus, 
  Mail, 
  Lock, 
  User,
  Eye,
  EyeOff,
  Loader2,
  AlertCircle,
  KeyRound
} from 'lucide-react';
import api, { ApiError, type DemoAccountHint } from '@/lib/api';
import { clearSession, isOfflineDemoSession, OFFLINE_DEMO_TOKEN, storeSession, type SessionUser } from '@/lib/session';
import { OFFLINE_DEMO_CREDENTIALS } from '@/lib/offlineDemo';
import useStore from '@/store/useStore';
import BrandLogo from '@/components/BrandLogo';

export default function LoginPage() {
  const router = useRouter();
  const [isLogin, setIsLogin] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [demoAccount, setDemoAccount] = useState<DemoAccountHint | null>(null);

  // A deployment that seeded a demo account publishes its credentials here so
  // a first-time visitor is not staring at a form they have no account for.
  // It resolves to null whenever there is nothing to offer.
  useEffect(() => {
    let active = true;
    api.getDemoAccount().then((hint) => {
      if (active) {
        setDemoAccount(hint);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const fillWithDemoAccount = () => {
    if (!demoAccount) {
      return;
    }
    setFormData((current) => ({
      ...current,
      username: demoAccount.username,
      password: demoAccount.password,
    }));
    setError('');
  };
  
  // Form data
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: ''
  });

  // Both real and offline sessions need the cookie for workspace navigation;
  // the API transport keeps the offline marker entirely inside the frontend.
  const enterWorkspace = (accessToken: string, user: SessionUser) => {
    storeSession(accessToken, user, useStore.getState().clearAccountState);
    router.push('/');
  };

  const enterOfflineDemo = () => {
    enterWorkspace(OFFLINE_DEMO_TOKEN, { username: 'demo', email: 'demo@example.com' });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Signing in from a demo tab is a deliberate account transition, not a
      // request to authenticate with the preview's frontend-only identity.
      if (isOfflineDemoSession()) {
        useStore.getState().clearAccountState();
        clearSession();
      }
      if (isLogin) {
        const { access_token: accessToken } = await api.login({
          username: formData.username,
          password: formData.password,
        });

        // The token only carries the username, so ask the backend for the
        // account the workspace displays. A hiccup here must not block sign-in.
        const account = await api.getAccount(accessToken).catch(() => null);

        enterWorkspace(accessToken, {
          username: account?.username || formData.username,
          email: account?.email || '',
        });
      } else {
        if (formData.password !== formData.confirmPassword) {
          throw new Error('Passwords do not match');
        }

        await api.register({
          username: formData.username,
          email: formData.email,
          password: formData.password,
        });

        try {
          const { access_token: accessToken } = await api.login({
            username: formData.username,
            password: formData.password,
          });
          enterWorkspace(accessToken, {
            username: formData.username,
            email: formData.email,
          });
        } catch {
          // The account exists; only the follow-up sign-in failed.
          setIsLogin(true);
          setError('Registration successful! Please login.');
        }
      }
    } catch (err: unknown) {
      const demoCandidate = isLogin
        && formData.username === OFFLINE_DEMO_CREDENTIALS.username
        && formData.password === OFFLINE_DEMO_CREDENTIALS.password;
      const unavailable = err instanceof TypeError
        || ((err instanceof Error || err instanceof DOMException) && err.name === 'AbortError')
        || (err instanceof ApiError && [500, 502, 503, 504].includes(err.status));
      if (demoCandidate && unavailable) {
        enterOfflineDemo();
        return;
      }
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
    setError(''); // Clear error on input change
  };

  return (
    <main className="auth-page flex min-h-dvh items-center justify-center px-4 py-12 sm:px-6">
      <div className="w-full max-w-md">
        {/* Logo/Title */}
        <div className="text-center mb-8">
          <BrandLogo
            className="mx-auto mb-4 h-10 w-10"
          />
          <h1 className="text-xl font-medium text-[var(--foreground)]">
            OpenNotebookLM
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-2">
            Research grounded in your sources
          </p>
        </div>

        {/* Form Card */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-6 sm:p-8">
          <h2 id="auth-heading" className="mb-6 text-2xl font-medium leading-tight">
            {isLogin ? 'Sign in to your workspace' : 'Create your account'}
          </h2>
          {isLogin && demoAccount && (
            <div
              data-testid="demo-account-hint"
              className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--muted)] p-3"
            >
              <div className="flex items-start gap-2">
                <KeyRound className="mt-0.5 w-4 h-4 shrink-0 text-[var(--foreground)]" />
                <div className="text-sm text-[var(--foreground)]">
                  <p className="font-medium">You can sign in with the demo account</p>
                  <p className="mt-1 font-mono text-xs break-all">
                    {demoAccount.username} / {demoAccount.password}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={fillWithDemoAccount}
                className="mt-3 w-full py-1.5 px-3 rounded-md border border-[var(--border)] text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] transition-colors"
              >
                Use demo account
              </button>
            </div>
          )}
          <form onSubmit={handleSubmit} aria-labelledby="auth-heading" className="space-y-5">
            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-[var(--muted-foreground)] mb-1"
              >
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[var(--muted-foreground)]" />
                <input
                  type="text"
                  id="username"
                  name="username"
                  autoComplete="username"
                  value={formData.username}
                  onChange={handleInputChange}
                  required
                  className="h-11 w-full rounded-lg border border-[var(--input)] bg-[var(--card)] pl-10 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
                  placeholder="Enter username"
                />
              </div>
            </div>

            {/* Email (Register only) */}
            {!isLogin && (
              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-[var(--muted-foreground)] mb-1"
                >
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[var(--muted-foreground)]" />
                  <input
                    type="email"
                    id="email"
                    name="email"
                    autoComplete="email"
                    value={formData.email}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="h-11 w-full rounded-lg border border-[var(--input)] bg-[var(--card)] pl-10 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
                    placeholder="Enter email"
                  />
                </div>
              </div>
            )}

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-[var(--muted-foreground)] mb-1"
              >
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[var(--muted-foreground)]" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  name="password"
                  autoComplete={isLogin ? 'current-password' : 'new-password'}
                  value={formData.password}
                  onChange={handleInputChange}
                  required
                  className="h-11 w-full rounded-lg border border-[var(--input)] bg-[var(--card)] pl-10 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
                  placeholder="Enter password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  title={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] transition-base"
                >
                  {showPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Confirm Password (Register only) */}
            {!isLogin && (
              <div>
                <label
                  htmlFor="confirmPassword"
                  className="block text-sm font-medium text-[var(--muted-foreground)] mb-1"
                >
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-[var(--muted-foreground)]" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    id="confirmPassword"
                    name="confirmPassword"
                    autoComplete="new-password"
                    value={formData.confirmPassword}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="h-11 w-full rounded-lg border border-[var(--input)] bg-[var(--card)] pl-10 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-base"
                    placeholder="Confirm password"
                  />
                </div>
              </div>
            )}

            {/* Error Message */}
            {error && (
              <div role="alert" className="flex items-center gap-2 p-3 bg-[var(--error-bg)] border border-[var(--error)] rounded-lg text-[var(--error)]">
                <AlertCircle className="w-5 h-5" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] hover:bg-[var(--primary-hover)] disabled:cursor-not-allowed disabled:opacity-50 transition-base"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>{isLogin ? 'Logging in...' : 'Creating account...'}</span>
                </>
              ) : (
                <>
                  {isLogin ? (
                    <LogIn className="w-5 h-5" />
                  ) : (
                    <UserPlus className="w-5 h-5" />
                  )}
                  <span>{isLogin ? 'Login' : 'Register'}</span>
                </>
              )}
            </button>
          </form>

          {isLogin && (
            <p className="mt-4 text-center text-xs leading-relaxed text-[var(--muted-foreground)]">
              Demo: demo / demo1234 · Works without a backend
            </p>
          )}

          {/* Toggle Login/Register */}
          <div className="mt-6 text-center">
            <p className="text-sm text-[var(--muted-foreground)]">
              {isLogin ? "Don't have an account?" : 'Already have an account?'}
              <button
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError('');
                  setFormData({
                    username: '',
                    email: '',
                    password: '',
                    confirmPassword: ''
                  });
                }}
                className="ml-2 text-[var(--foreground)] font-medium underline underline-offset-2 decoration-[var(--input)] hover:decoration-current"
              >
                {isLogin ? 'Register' : 'Login'}
              </button>
            </p>
          </div>

        </div>
      </div>
    </main>
  );
}
