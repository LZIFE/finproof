import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinProof 鉴融",
  description: "金融研究报告事实核验与证据链智能体",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
