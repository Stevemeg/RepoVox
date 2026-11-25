import { humanize } from "@/lib/format";

export type Tone =
  | "neutral"
  | "running"
  | "succeeded"
  | "failed"
  | "warning"
  | "verified"
  | "inferred"
  | "author-stated"
  | "unverified";

const STATE_TONES: Record<string, Tone> = {
  running: "running",
  ready: "running",
  succeeded: "succeeded",
  failed: "failed",
  cancelled: "neutral",
  queued: "warning",
  retry_wait: "warning",
  awaiting_analysis: "warning",
  pending: "neutral",
  unprocessed: "neutral",
};

export const toneFor = (state: string): Tone => STATE_TONES[state] ?? "neutral";

/** A state rendered as text, never colour alone. */
export function Badge({ state, label }: { state: string; label?: string }) {
  return (
    <span className="badge" data-tone={toneFor(state)}>
      <span className="badge-dot" aria-hidden="true" />
      {label ?? humanize(state)}
    </span>
  );
}
