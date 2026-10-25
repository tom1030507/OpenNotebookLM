'use client';

import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ComponentType<{ error: Error; reset: () => void }>;
}

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  reset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        const FallbackComponent = this.props.fallback;
        return <FallbackComponent error={this.state.error} reset={this.reset} />;
      }

      return <DefaultErrorFallback error={this.state.error} reset={this.reset} />;
    }

    return this.props.children;
  }
}

function DefaultErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--muted)] px-4">
      <div className="max-w-md w-full">
        <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-6">
          <div className="flex items-center justify-center w-12 h-12 mx-auto bg-[var(--error-bg)] rounded-full">
            <AlertTriangle className="w-6 h-6 text-[var(--error)]" />
          </div>
          
          <h1 className="mt-4 text-xl font-semibold text-center text-[var(--foreground)]">
            Something went wrong
          </h1>
          
          <p className="mt-2 text-sm text-center text-[var(--muted-foreground)]">
            An unexpected error occurred. Please try again or contact support if the problem persists.
          </p>

          {process.env.NODE_ENV === 'development' && (
            <details className="mt-4 p-4 bg-[var(--muted)] rounded-lg">
              <summary className="text-sm font-medium text-[var(--muted-foreground)] cursor-pointer">
                Error details
              </summary>
              <pre className="mt-2 text-xs text-[var(--muted-foreground)] overflow-auto">
                {error.stack || error.message}
              </pre>
            </details>
          )}

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => window.location.href = '/'}
              className="flex-1 px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] bg-[var(--muted)] rounded-lg hover:bg-[var(--muted)] transition-colors"
            >
              Go Home
            </button>
            <button
              onClick={reset}
              className="flex-1 px-4 py-2 text-sm font-medium text-white bg-[var(--primary)] rounded-lg hover:bg-[var(--primary-hover)] transition-colors flex items-center justify-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              Try Again
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ErrorBoundary;
