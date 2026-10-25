import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import NotificationProvider from "@/components/NotificationProvider";
import { initializeTheme } from "@/lib/theme";
import "./globals.css";
import 'katex/dist/katex.min.css';

const themeInitializationScript = `(${initializeTheme.toString()})();`;

// next/font downloads the files at build time and serves them from this app,
// so a self-hosted instance never calls out to Google Fonts at runtime.
const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

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
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`} suppressHydrationWarning>
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
