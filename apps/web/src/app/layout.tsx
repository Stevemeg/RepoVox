import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'RepoVox · Bring source code to life visually',
  description: 'Your local workspace for source-code stories. Phase 1 development foundation.'};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
