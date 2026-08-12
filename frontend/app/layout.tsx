import type { Metadata } from "next";
import NotificationProvider from "@/components/NotificationProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: 'OpenNotebookLM - AI 知識助理',
  description: '將你的文件轉換為可互動的 AI 對話',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-TW">
      <body className="antialiased">
        <NotificationProvider />
        {children}
      </body>
    </html>
  );
}
