/** Accessible loading state while a route segment renders on the server. */
export default function Loading() {
  return (
    <main className="status-page" aria-busy="true">
      <div className="status-card">
        <p role="status" className="visually-hidden">
          Loading…
        </p>
        <div className="skeleton-stack" aria-hidden="true">
          <span className="skeleton" />
          <span className="skeleton" />
          <span className="skeleton" />
        </div>
      </div>
    </main>
  );
}
