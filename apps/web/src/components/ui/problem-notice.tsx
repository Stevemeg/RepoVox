import type { Problem } from "@/lib/errors";

/**
 * An error in our own words. The API's fixed code and request id appear only as muted
 * support metadata after the message, never as the message itself.
 */
export function ProblemNotice({
  problem,
  onRetry,
  retryLabel = "Try again",
}: {
  problem: Problem;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  const reference = [
    problem.code !== "client_error" ? problem.code : null,
    problem.requestId ? `request ${problem.requestId}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="problem" role="alert">
      <div className="problem-body">
        <p className="problem-message">{problem.message}</p>
        {reference && <small className="problem-meta">Reference: {reference}</small>}
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          {retryLabel}
        </button>
      )}
    </div>
  );
}
