"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="fatal">
      <h1>Something went wrong</h1>
      <p>This view could not load. Please try again.</p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
