'use client';
export default function ErrorPage({reset}: {reset: () => void}) {
  return <main className="fatal"><h1>Something went wrong</h1><p>Your records are still stored safely. Please reload this view.</p><button onClick={reset}>Try again</button></main>;
}
