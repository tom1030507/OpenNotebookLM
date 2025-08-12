'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check } from 'lucide-react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export default function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
  const [copiedCode, setCopiedCode] = React.useState<string | null>(null);

  const copyToClipboard = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <ReactMarkdown
      className={`prose prose-sm dark:prose-invert max-w-none ${className}`}
      remarkPlugins={[remarkGfm]}
      components={{
        // Custom code block rendering
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '');
          const language = match ? match[1] : '';
          const codeString = String(children).replace(/\n$/, '');

          if (!inline && language) {
            return (
              <div className="relative group">
                <button
                  className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity p-2 bg-gray-700 hover:bg-gray-600 rounded"
                  onClick={() => copyToClipboard(codeString)}
                  title="Copy code"
                >
                  {copiedCode === codeString ? (
                    <Check className="w-4 h-4 text-green-400" />
                  ) : (
                    <Copy className="w-4 h-4 text-gray-300" />
                  )}
                </button>
                <SyntaxHighlighter
                  style={vscDarkPlus}
                  language={language}
                  PreTag="div"
                  customStyle={{
                    margin: 0,
                    borderRadius: '0.375rem',
                    fontSize: '0.875rem',
                  }}
                  {...props}
                >
                  {codeString}
                </SyntaxHighlighter>
              </div>
            );
          }

          return (
            <code className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-sm" {...props}>
              {children}
            </code>
          );
        },
        // Custom link rendering
        a({ href, children }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 dark:text-blue-400 hover:underline"
            >
              {children}
            </a>
          );
        },
        // Custom table rendering
        table({ children }) {
          return (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                {children}
              </table>
            </div>
          );
        },
        thead({ children }) {
          return (
            <thead className="bg-gray-50 dark:bg-gray-800">
              {children}
            </thead>
          );
        },
        th({ children }) {
          return (
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              {children}
            </th>
          );
        },
        td({ children }) {
          return (
            <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
              {children}
            </td>
          );
        },
        // Custom blockquote rendering
        blockquote({ children }) {
          return (
            <blockquote className="border-l-4 border-gray-300 dark:border-gray-600 pl-4 my-4 italic text-gray-700 dark:text-gray-300">
              {children}
            </blockquote>
          );
        },
        // Custom list rendering
        ul({ children }) {
          return (
            <ul className="list-disc list-inside space-y-1 my-4">
              {children}
            </ul>
          );
        },
        ol({ children }) {
          return (
            <ol className="list-decimal list-inside space-y-1 my-4">
              {children}
            </ol>
          );
        },
        // Custom heading rendering
        h1({ children }) {
          return (
            <h1 className="text-2xl font-bold mt-6 mb-4 text-gray-900 dark:text-gray-100">
              {children}
            </h1>
          );
        },
        h2({ children }) {
          return (
            <h2 className="text-xl font-semibold mt-5 mb-3 text-gray-900 dark:text-gray-100">
              {children}
            </h2>
          );
        },
        h3({ children }) {
          return (
            <h3 className="text-lg font-medium mt-4 mb-2 text-gray-900 dark:text-gray-100">
              {children}
            </h3>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
