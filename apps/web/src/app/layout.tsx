import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "RepoVox · Bring source code to life visually",
    template: "%s · RepoVox",
  },
  description:
    "Evidence-grounded, narrated walkthroughs of public GitHub repositories. RepoVox reads one pinned commit as data and never runs it.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1d6a4d",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
