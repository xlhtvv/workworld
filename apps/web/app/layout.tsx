import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorkWorld",
  description: "A framework-neutral market for provider-hosted Agents"
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
