'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Copy, Check } from 'lucide-react';
import type { Citation, CitationCheck } from '@/lib/api';
import { citationId, rehypeCitations } from '@/lib/citations';
import InlineCitation from './InlineCitation';

interface HighlightedCodeProps {
  code: string;
  language: string;
}

const HighlightedCode = React.lazy(
  async () => {
    const [{ Prism }, { vscDarkPlus }] = await Promise.all([
      import('react-syntax-highlighter'),
      import('react-syntax-highlighter/dist/esm/styles/prism'),
    ]);

    return {
      default: function HighlightedCodeBlock({ code, language }: HighlightedCodeProps) {
        return (
          <Prism
            style={vscDarkPlus as { [selector: string]: React.CSSProperties }}
            language={language}
            PreTag="div"
            customStyle={{
              margin: 0,
              borderRadius: '0.375rem',
              fontSize: '0.875rem',
            }}
          >
            {code}
          </Prism>
        );
      },
    };
  },
);

interface MarkdownRendererProps {
  content: string;
  className?: string;
  citations?: Citation[];
  citationLabels?: Map<number, number>;
  citationChecks?: CitationCheck[];
}

function transformMathText(text: string): string {
  return text
    // Preserve prices so a later math delimiter cannot pair with the dollar.
    .replace(/(^|[\s(])\$(?=\s?\d[\d,]*(?:\.\d+)?(?:[\s),.;:/!?]|$))/g, '$1\\$')
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, formula: string) => (
      `\n\n$$\n${formula.trim()}\n$$\n\n`
    ))
    .replace(/\\\(([^\r\n]*?)\\\)/g, (_match, formula: string) => `$${formula}$`);
}

function prepareMathMarkdown(markdown: string): string {
  let result = '';
  let text = '';
  let fence: { marker: string; length: number } | null = null;
  const lines = markdown.match(/[^\n]*\n|[^\n]+$/g) ?? [];

  for (const line of lines) {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/)?.[1];
    if (fence) {
      result += line;
      if (
        marker
        && marker[0] === fence.marker
        && marker.length >= fence.length
        && /^ {0,3}(?:`{3,}|~{3,})[ \t]*\r?\n?$/.test(line)
      ) {
        fence = null;
      }
      continue;
    }

    if (marker) {
      result += prepareMathText(text) + line;
      text = '';
      fence = { marker: marker[0], length: marker.length };
    } else if (/^(?: {4}|\t)/.test(line)) {
      result += prepareMathText(text) + line;
      text = '';
    } else {
      text += line;
    }
  }

  return result + prepareMathText(text);
}

function prepareMathText(text: string): string {
  // Delimiters inside inline code are literal Markdown content.
  const codeSpan = /(`+)[\s\S]*?\1/g;
  let result = '';
  let offset = 0;

  for (const match of text.matchAll(codeSpan)) {
    const start = match.index ?? 0;
    result += transformMathText(text.slice(offset, start)) + match[0];
    offset = start + match[0].length;
  }

  return result + transformMathText(text.slice(offset));
}

export default function MarkdownRenderer({
  content,
  className = '',
  citations,
  citationLabels,
  citationChecks,
}: MarkdownRendererProps) {
  const [copiedCode, setCopiedCode] = React.useState<string | null>(null);
  const citationsById = React.useMemo(() => {
    const byId = new Map<number, Citation>();
    for (const citation of citations ?? []) {
      const id = citationId(citation);
      if (id !== null) byId.set(id, citation);
    }
    return byId;
  }, [citations]);

  const copyToClipboard = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <div className={`prose prose-sm max-w-none ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeCitations, {
          ids: new Set(citationsById.keys()),
          citationLabels,
          citationChecks,
        }], rehypeKatex]}
        components={{
        // A language block renders its own fallback/highlighter container.
        // Keep ReactMarkdown's pre for ordinary fenced code, but unwrap this
        // case so a fallback owns one valid <pre><code> pair.
        pre({ children }) {
          const child = React.Children.toArray(children)[0];
          const languageBlock = React.isValidElement<{ className?: string }>(child)
            && /language-\w+/.test(child.props.className || '');

          return languageBlock ? <>{children}</> : <pre>{children}</pre>;
        },
        // Custom code block rendering
        code({ node, className, children, ...props }) {
          void node;
          const match = /language-(\w+)/.exec(className || '');
          const language = match ? match[1] : '';
          const codeString = String(children).replace(/\n$/, '');

          if (language) {
            return (
              <div className="relative group">
                <button
                  className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity p-2 bg-gray-700 hover:bg-gray-600 rounded"
                  onClick={() => copyToClipboard(codeString)}
                  aria-label="Copy code"
                  title="Copy code"
                >
                  {copiedCode === codeString ? (
                    <Check className="w-4 h-4 text-green-400" />
                  ) : (
                    <Copy className="w-4 h-4 text-gray-300" />
                  )}
                </button>
                <React.Suspense
                  fallback={<pre className="m-0 rounded-md text-sm"><code>{codeString}</code></pre>}
                >
                  <HighlightedCode code={codeString} language={language} />
                </React.Suspense>
              </div>
            );
          }

          return (
            <code className="px-1.5 py-0.5 bg-[var(--muted)] rounded text-sm" {...props}>
              {children}
            </code>
          );
        },
        // Custom link rendering
        a({ href, children, node }) {
          const id = node?.properties['data-citation-id'];
          const citation = typeof id === 'number' ? citationsById.get(id) : undefined;
          if (typeof id === 'number' && citation) {
            return <InlineCitation
              id={citationLabels?.get(id) ?? id}
              citation={citation}
            />;
          }
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--foreground)] underline underline-offset-2 decoration-[var(--input)] hover:decoration-current"
            >
              {children}
            </a>
          );
        },
        // Custom table rendering
        table({ children }) {
          return (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full divide-y divide-[var(--border)]">
                {children}
              </table>
            </div>
          );
        },
        thead({ children }) {
          return (
            <thead>
              {children}
            </thead>
          );
        },
        th({ children }) {
          return (
            <th className="px-4 py-2 text-left text-xs font-normal text-[var(--muted-foreground)]">
              {children}
            </th>
          );
        },
        td({ children }) {
          return (
            <td className="px-4 py-2 whitespace-nowrap text-sm text-[var(--foreground)]">
              {children}
            </td>
          );
        },
        // Custom blockquote rendering
        blockquote({ children }) {
          return (
            <blockquote className="border-l-4 border-[var(--input)] pl-4 my-4 italic text-[var(--muted-foreground)]">
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
            <h1 className="text-lg font-semibold mt-5 mb-3 text-[var(--foreground)]">
              {children}
            </h1>
          );
        },
        h2({ children }) {
          return (
            <h2 className="text-base font-semibold mt-4 mb-2 text-[var(--foreground)]">
              {children}
            </h2>
          );
        },
        h3({ children }) {
          return (
            <h3 className="text-sm font-semibold mt-3 mb-1.5 text-[var(--foreground)]">
              {children}
            </h3>
          );
        },
        }}
      >
        {prepareMathMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}
