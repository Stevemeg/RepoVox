"use client";
import Link from "next/link";

/** Route-segment error boundary. Never shows the error's own message to the viewer. */
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="status-page">
      <div className="status-card" role="alert">
        <h1>Something went wrong</h1>
        <p>This view could not load. Try again, or return to your workspace.</p>
        <div className="actions">
          <button type="button" className="button-primary" onClick={reset}>
            Try again
          </button>
          <Link className="button" href="/">
            Go to Overview
          </Link>
        </div>
      </div>
    </main>
  );
}
