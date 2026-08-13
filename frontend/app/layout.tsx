import type { Metadata } from "next";
import NotificationProvider from "@/components/NotificationProvider";
import { initializeTheme } from "@/lib/theme";
import "./globals.css";

const themeInitializationScript = `(${initializeTheme.toString()})();`;

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
    <html lang="en" suppressHydrationWarning>
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
