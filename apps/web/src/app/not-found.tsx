import type { Metadata } from "next";
import Link from "next/link";
import { Brand } from "@/components/brand";

export const metadata: Metadata = { title: "Page not found" };

/**
 * Unknown paths render this with HTTP 404. A malformed project or job id renders it too
 * (the record pages call notFound() before any API request).
 */
export default function NotFound() {
  return (
    <main className="status-page">
      <div className="status-card">
        <Brand />
        <p className="status-code">404</p>
        <h1>Page not found</h1>
        <p>This page does not exist. Check the address, or go back to your workspace.</p>
        <nav aria-label="Recovery" className="actions">
          <Link className="button button-primary" href="/">
            Go to Overview
          </Link>
          <Link className="button" href="/projects">
            Go to your projects
          </Link>
        </nav>
      </div>
    </main>
  );
}
