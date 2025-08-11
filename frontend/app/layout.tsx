import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="zh-TW">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
