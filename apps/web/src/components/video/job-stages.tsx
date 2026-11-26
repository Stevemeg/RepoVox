import { Badge, type Tone } from "@/components/ui/badge";
import { humanize } from "@/lib/format";
import type { VideoStage } from "@/lib/types";

/*
 * The six media stages of a video job (`storyboard`, `narration`, `tts`, `render`, `encode`,
 * `architecture`), each with its own state as text.
 */

const STAGE_LABELS: Record<string, string> = {
  storyboard: "Storyboard",
  narration: "Narration",
  tts: "Speech",
  render: "Rendering",
  encode: "Encoding",
  architecture: "Architecture",
};

const STATE_LABELS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  ready: { label: "Ready", tone: "running" },
  running: { label: "Running", tone: "running" },
  retry_wait: { label: "Waiting to retry", tone: "warning" },
  succeeded: { label: "Succeeded", tone: "succeeded" },
  failed: { label: "Failed", tone: "failed" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const ACTIVE_STAGE = new Set(["ready", "running", "retry_wait"]);

export const stageLabel = (key: string) => STAGE_LABELS[key] ?? humanize(key);

export const orderedStages = (stages: readonly VideoStage[]) =>
  [...stages].sort((a, b) => a.ordinal - b.ordinal);

/** The stage being worked on, or null. */
export function currentStage(stages: readonly VideoStage[]): VideoStage | null {
  return orderedStages(stages).find((stage) => ACTIVE_STAGE.has(stage.state)) ?? null;
}

export function JobStages({ stages }: { stages: readonly VideoStage[] }) {
  const ordered = orderedStages(stages);
  const done = ordered.filter((stage) => stage.state === "succeeded").length;
  if (ordered.length === 0) return null;
  return (
    <div className="video-stages">
      <progress
        className="stage-progress"
        max={ordered.length}
        value={done}
        aria-label={`${done} of ${ordered.length} stages succeeded`}
      />
      <ol className="video-stage-list" aria-label="Production stages">
        {ordered.map((stage) => {
          const state = STATE_LABELS[stage.state] ?? { label: humanize(stage.state), tone: "neutral" as Tone };
          return (
            <li key={stage.ordinal} data-stage={stage.stage_key} data-state={stage.state}>
              <span className="video-stage-name">{stageLabel(stage.stage_key)}</span>
              <Badge state={stage.state} label={state.label} tone={state.tone} />
              {stage.attempt_count > 1 && (
                <small className="field-hint">attempt {stage.attempt_count}</small>
              )}
              {stage.error_code && (
                <small className="problem-meta">Reference: {stage.error_code}</small>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
