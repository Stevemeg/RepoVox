"use client";
import "./globals.css";

/**
 * Root error boundary: replaces the root layout when it fails, so it renders its own
 * document. The error's message and digest are never shown.
 */
export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <main className="status-page">
          <div className="status-card" role="alert">
            <h1>RepoVox could not load</h1>
            <p>Something went wrong while opening the app. Try again in a moment.</p>
            <div className="actions">
              <button type="button" className="button-primary" onClick={reset}>
                Try again
              </button>
              {/* A full navigation: the client router may be the part that failed. */}
              <a className="button" href="/">
                Reload RepoVox
              </a>
            </div>
          </div>
        </main>
      </body>
    </html>
  );
}
