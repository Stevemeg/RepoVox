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

/**
 * A state rendered as text, never colour alone. `tone` overrides the state's colour when the
 * meaning differs from the raw state, for example a job recorded as `failed` at a normal
 * pipeline boundary; `data-state` always carries the raw value.
 */
export function Badge({ state, label, tone }: { state: string; label?: string; tone?: Tone }) {
  return (
    <span className="badge" data-tone={tone ?? toneFor(state)} data-state={state}>
      <span className="badge-dot" aria-hidden="true" />
      {label ?? humanize(state)}
    </span>
  );
}
