'use client';

import React, { useState } from 'react';
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
  AlertCircle
} from 'lucide-react';

export default function LoginPage() {
  const router = useRouter();
  const [isLogin, setIsLogin] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Form data
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: ''
  });

  // Demo login function for development
  const handleDemoLogin = async () => {
    setLoading(true);
    // Simulate login delay
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    // Store demo tokens
    localStorage.setItem('access_token', 'demo_token_' + Date.now());
    localStorage.setItem('auth_token', 'demo_token_' + Date.now());
    localStorage.setItem('user', JSON.stringify({ username: 'demo', email: 'demo@example.com' }));
    
    // Redirect to main app
    router.push('/');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    
    // Demo mode - bypass authentication
    if (formData.username === 'admin' && formData.password === 'admin123') {
      await handleDemoLogin();
      return;
    }

    try {
      if (isLogin) {
        // Login
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/token`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            username: formData.username,
            password: formData.password,
          }),
        });

        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.detail || '登入失敗');
        }

        const tokens = await response.json();
        
        // Store tokens
        localStorage.setItem('access_token', tokens.access_token);
        localStorage.setItem('refresh_token', tokens.refresh_token);
        localStorage.setItem('auth_token', tokens.access_token); // For API client
        
        // Redirect to main app
        router.push('/');
      } else {
        // Register
        if (formData.password !== formData.confirmPassword) {
          throw new Error('兩次輸入的密碼不一致');
        }

        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/register`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username: formData.username,
            email: formData.email,
            password: formData.password,
          }),
        });

        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.detail || '註冊失敗');
        }

        // Auto-login after registration
        const loginResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/token`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            username: formData.username,
            password: formData.password,
          }),
        });

        if (loginResponse.ok) {
          const tokens = await loginResponse.json();
          localStorage.setItem('access_token', tokens.access_token);
          localStorage.setItem('refresh_token', tokens.refresh_token);
          localStorage.setItem('auth_token', tokens.access_token);
          router.push('/');
        } else {
          // Registration successful but login failed
          setIsLogin(true);
          setError('註冊成功！請登入。');
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '發生錯誤');
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
          <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gradient-to-br from-purple-500 to-purple-700 flex items-center justify-center">
            <span className="text-3xl font-bold text-white">ON</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            OpenNotebookLM
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
            {isLogin ? '歡迎回來！' : '建立你的帳號'}
          </p>
        </div>

        {/* Form Card */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-8">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                使用者名稱
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  name="username"
                  value={formData.username}
                  onChange={handleInputChange}
                  required
                  className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                  placeholder="輸入使用者名稱"
                />
              </div>
            </div>

            {/* Email (Register only) */}
            {!isLogin && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  電子郵件
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="email"
                    name="email"
                    value={formData.email}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                    placeholder="輸入電子郵件"
                  />
                </div>
              </div>
            )}

            {/* Password */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                密碼
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  value={formData.password}
                  onChange={handleInputChange}
                  required
                  className="w-full pl-10 pr-10 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                  placeholder="輸入密碼"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
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
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  確認密碼
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="confirmPassword"
                    value={formData.confirmPassword}
                    onChange={handleInputChange}
                    required={!isLogin}
                    className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600"
                    placeholder="再次輸入密碼"
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
                  <span>{isLogin ? '登入中...' : '建立帳號中...'}</span>
                </>
              ) : (
                <>
                  {isLogin ? (
                    <LogIn className="w-5 h-5" />
                  ) : (
                    <UserPlus className="w-5 h-5" />
                  )}
                  <span>{isLogin ? '登入' : '註冊'}</span>
                </>
              )}
            </button>
          </form>

          {/* Toggle Login/Register */}
          <div className="mt-6 text-center">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {isLogin ? '還沒有帳號嗎？' : '已經有帳號了嗎？'}
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
                {isLogin ? '註冊' : '登入'}
              </button>
            </p>
          </div>

          {/* Demo Credentials */}
          {isLogin && (
            <div className="mt-4 space-y-2">
              <div className="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <p className="text-xs text-gray-600 dark:text-gray-400 mb-1">
                  示範帳號：
                </p>
                <p className="text-xs font-mono text-gray-700 dark:text-gray-300">
                  使用者名稱：admin｜密碼：admin123
                </p>
              </div>
              
              {/* Quick Demo Access Button */}
              <button
                type="button"
                onClick={async () => {
                  // Directly call demo login
                  await handleDemoLogin();
                }}
                className="w-full py-2 px-4 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors text-sm"
              >
                快速體驗
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
