import type { Metadata } from "next";
import NotificationProvider from "@/components/NotificationProvider";
import "./globals.css";

const themeInitializationScript = `
  try {
    const storageKey = 'open-notebook-theme';
    const storedTheme = window.localStorage.getItem(storageKey);
    const theme = storedTheme === 'light' || storedTheme === 'dark'
      ? storedTheme
      : window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  } catch {
    const theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }
`;

export const metadata: Metadata = {
  title: "OpenNotebookLM - AI-Powered Knowledge Assistant",
  description: "Transform your documents into interactive conversations with AI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-TW" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitializationScript }} />
      </head>
      <body className="antialiased">
        <NotificationProvider />
        {children}
      </body>
    </html>
  );
}
