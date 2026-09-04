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
import api, { type DemoAccountHint } from '@/lib/api';
import { storeSession, type SessionUser } from '@/lib/session';
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

  // Open the workspace with the session recorded for both the client and the
  // server-side middleware. Every API route refuses a token the backend did not
  // issue, so this is only ever reached with a real one.
  const enterWorkspace = (accessToken: string, user: SessionUser) => {
    storeSession(accessToken, user, useStore.getState().clearAccountState);
    router.push('/');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-purple-50 to-purple-100 dark:from-gray-900 dark:to-gray-800">
      <div className="w-full max-w-md">
        {/* Logo/Title */}
        <div className="text-center mb-8">
          <BrandLogo
            className="w-20 h-20 mx-auto mb-4"
          />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            OpenNotebookLM
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
            {isLogin ? 'Welcome back!' : 'Create your account'}
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8">
          {isLogin && demoAccount && (
            <div
              data-testid="demo-account-hint"
              className="mb-4 rounded-lg border border-purple-200 bg-purple-50 p-3 dark:border-purple-800 dark:bg-purple-900/30"
            >
              <div className="flex items-start gap-2">
                <KeyRound className="mt-0.5 w-4 h-4 shrink-0 text-purple-600 dark:text-purple-300" />
                <div className="text-sm text-purple-900 dark:text-purple-100">
                  <p className="font-medium">You can sign in with the demo account</p>
                  <p className="mt-1 font-mono text-xs break-all">
                    {demoAccount.username} / {demoAccount.password}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={fillWithDemoAccount}
                className="mt-3 w-full py-1.5 px-3 rounded-md border border-purple-300 text-sm font-medium text-purple-700 hover:bg-purple-100 transition-colors dark:border-purple-700 dark:text-purple-200 dark:hover:bg-purple-800/40"
              >
                Use demo account
              </button>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  id="username"
                  name="username"
                  value={formData.username}
                  onChange={handleInputChange}
                  required
                  className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                  placeholder="Enter username"
                />
              </div>
            </div>

            {/* Email (Register only) */}
            {!isLogin && (
              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                >
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="email"
                    id="email"
                    name="email"
                    value={formData.email}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                    placeholder="Enter email"
                  />
                </div>
              </div>
            )}

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  name="password"
                  value={formData.password}
                  onChange={handleInputChange}
                  required
                  className="w-full pl-10 pr-10 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                  placeholder="Enter password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  title={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
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
                  className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
                >
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    id="confirmPassword"
                    name="confirmPassword"
                    value={formData.confirmPassword}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                    placeholder="Confirm password"
                  />
                </div>
              </div>
            )}

            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700">
                <AlertCircle className="w-5 h-5" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2 px-4 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
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

          {/* Toggle Login/Register */}
          <div className="mt-6 text-center">
            <p className="text-sm text-gray-600 dark:text-gray-400">
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
                className="ml-2 text-purple-600 hover:text-purple-700 font-medium"
              >
                {isLogin ? 'Register' : 'Login'}
              </button>
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}
