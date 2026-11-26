"use client";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { RemediationPanel } from "@/components/ui/remediation-panel";
import { SkeletonRows } from "@/components/ui/states";
import { currentStage, JobStages, stageLabel } from "@/components/video/job-stages";
import { VideoStudio } from "@/components/video/video-studio";
import { WorkspaceContext } from "@/components/workspace/context";
import { StatusBadge } from "@/components/workspace/records";
import { useAction } from "@/components/workspace/use-action";
import { api, ApiError, type Video, type VideoJob } from "@/lib/api";
import { describeJobOutcome, toProblem, type Problem } from "@/lib/errors";
import { formatDateTime, shortId, TERMINAL_VIDEO_STATES } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { videoJobStatus } from "@/lib/job-status";
import { isUuid } from "@/lib/security";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";

export type { Video, VideoJob };
// Re-exported for existing importers; the routes now live with the other media helpers.
export { videoRoutes } from "@/lib/video-media";

const REFRESH_MS = 3000;

// The architecture outcome is reported separately from the walkthrough. A published
// walkthrough never implies that an architecture explainer was produced.
const architectureNotes: Record<string, string> = {
  published: "Architecture explainers were generated from verified source relationships.",
  unsupported:
    "No architecture explainer: the source evidence was not sufficient to establish one.",
  extraction_failed:
    "No architecture explainer: architecture extraction failed. The walkthrough is unaffected.",
  rendering_failed:
    "No architecture explainer: an architecture was found but rendering it failed. The walkthrough is unaffected.",
  not_completed:
    "No architecture explainer: the architecture stage did not complete. The walkthrough is unaffected.",
};

const architectureNote = (job: VideoJob): string =>
  (job.architecture && architectureNotes[job.architecture]) ||
  "Architecture outcome was not recorded.";

function progressNote(job: VideoJob): string {
  if (job.state === "awaiting_analysis") return "Waiting for verified static analysis to finish.";
  const stage = currentStage(job.stages);
  if (!stage) return "Working: starting.";
  const ordered = [...job.stages].sort((a, b) => a.ordinal - b.ordinal);
  const index = ordered.findIndex((item) => item.ordinal === stage.ordinal);
  return `Working: ${stageLabel(stage.stage_key)} (stage ${index + 1} of ${ordered.length}).`;
}

/** One video job: its status, progress, outcome and, once succeeded, its Video Studio. */
function VideoJobCard({
  job,
  busy,
  onCancel,
}: {
  job: VideoJob;
  busy: boolean;
  onCancel: () => void;
}) {
  const status = videoJobStatus(job);
  const outcome = describeJobOutcome(job.error_code);
  const terminal = TERMINAL_VIDEO_STATES.includes(job.state);
  const succeededStages = job.stages.filter((stage) => stage.state === "succeeded").length;
  return (
    <article
      className="video-job"
      aria-label={`Video job ${shortId(job.id)}`}
      data-state={job.state}
    >
      <header className="video-job-header">
        <h3>
          Video job <code className="sha">{shortId(job.id)}</code>
          <StatusBadge status={status} />
        </h3>
        <p className="video-job-meta">
          {job.repository && <span>{job.repository}</span>}
          {job.commit_sha && (
            <span>
              pinned commit <code className="sha">{job.commit_sha}</code>
            </span>
          )}
          <span>created {formatDateTime(job.created_at)}</span>
        </p>
      </header>
      {!terminal && (
        <>
          <p role="status">{progressNote(job)}</p>
          <JobStages stages={job.stages} />
          <div className="actions">
            <button type="button" disabled={busy} onClick={onCancel}>
              Cancel video job
            </button>
          </div>
        </>
      )}
      {outcome && (
        <div className="notice" data-tone="warning">
          <div>
            <p>{outcome}</p>
            <small className="problem-meta">Reference: {job.error_code}</small>
          </div>
        </div>
      )}
      {job.state === "failed" && (
        <>
          <RemediationPanel code={job.error_code} />
          <JobStages stages={job.stages} />
        </>
      )}
      {job.state === "succeeded" && (
        <>
          <p data-architecture={job.architecture ?? "unknown"}>{architectureNote(job)}</p>
          {job.stages.length > 0 && (
            <details className="disclosure">
              <summary>
                Production stages: {succeededStages} of {job.stages.length} succeeded
              </summary>
              <JobStages stages={job.stages} />
            </details>
          )}
          {job.videos.length > 0 ? (
            <VideoStudio job={job} />
          ) : (
            <p className="notice" data-tone="neutral">
              No videos are listed for this job. Published videos are available for 24 hours
              after their job was created, so they may have expired.
            </p>
          )}
        </>
      )}
    </article>
  );
}

/**
 * A project's narrated videos. `onJobs` receives each loaded list (or null when loading
 * failed) so the project page can describe the project truthfully. The section is the
 * `#videos` target that Job history links to: when the page was opened with that hash, the
 * section scrolls into view and takes focus once its jobs have loaded.
 */
export function VideoJobs({
  projectId,
  onJobs,
}: {
  projectId: string;
  onJobs?: (jobs: VideoJob[] | null) => void;
}) {
  const workspace = useContext(WorkspaceContext);
  const handleUnauthorized = workspace?.handleUnauthorized;
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadProblem, setLoadProblem] = useState<Problem | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const key = useIdempotencyKey();
  const action = useAction("video");
  const valid = isUuid(projectId);
  const report = useRef(onJobs);
  useEffect(() => {
    report.current = onJobs;
  });
  const section = useRef<HTMLElement>(null);
  const revealed = useRef(false);

  const load = useCallback(async () => {
    if (!valid) return;
    try {
      const found = await api<VideoJob[]>(`/projects/${projectId}/video-jobs`);
      setJobs(found);
      setLoadProblem(null);
      report.current?.(found);
    } catch (cause) {
      if (!handleUnauthorized?.(cause)) {
        setLoadProblem(toProblem(cause, "video"));
        report.current?.(null);
      }
    } finally {
      setLoaded(true);
    }
  }, [projectId, valid, handleUnauthorized]);
  const active = jobs.some((job) => !TERMINAL_VIDEO_STATES.includes(job.state));
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!loaded || revealed.current || window.location.hash !== "#videos") return;
    revealed.current = true;
    section.current?.scrollIntoView?.({ block: "start" });
    section.current?.focus({ preventScroll: true });
  }, [loaded]);
  // Display refresh only. Jobs advance on the server whether or not this page is open.
  useVisibilityPolling(load, REFRESH_MS, active);

  async function create() {
    let failure: unknown;
    const ok = await action.run(() =>
      api(`/projects/${projectId}/video-jobs`, {
        method: "POST",
        idempotencyKey: key.current(),
        body: JSON.stringify({ processing_acknowledged: true }),
      }).catch((cause: unknown) => {
        failure = cause;
        throw cause;
      }),
    );
    if (ok || (failure instanceof ApiError && failure.code === "idempotency_conflict"))
      key.rotate();
    if (ok) await load();
  }

  if (!valid) return null;
  return (
    <section
      ref={section}
      id="videos"
      tabIndex={-1}
      className="panel"
      aria-labelledby="narrated-videos"
      aria-busy={!loaded}
    >
      <div className="panel-header">
        <h2 id="narrated-videos">Narrated videos</h2>
      </div>
      <div className="panel-body video-jobs">
        <p>
          Creates a repository walkthrough and, where the source evidence supports it,
          architecture explainers. A public GitHub snapshot is analysed as data in local
          private storage for up to 24 hours, and repository code is never run.
        </p>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          I acknowledge this local source processing for video creation.
        </label>
        <div className="actions">
          <button
            type="button"
            className="button-primary"
            disabled={action.busy || !acknowledged || active}
            onClick={() => void create()}
          >
            Create narrated videos
          </button>
        </div>
        {action.problem && (
          <>
            <ProblemNotice problem={action.problem} />
            <RemediationPanel code={action.problem.code} context="request" compact />
          </>
        )}
        {loadProblem && <ProblemNotice problem={loadProblem} onRetry={() => void load()} />}
        {!loaded && <SkeletonRows rows={2} />}
        {jobs.map((job) => (
          <VideoJobCard
            key={job.id}
            job={job}
            busy={action.busy}
            onCancel={() =>
              void action
                .run(() => api(`/video-jobs/${job.id}/cancel`, { method: "POST" }))
                .then((ok) => (ok ? load() : undefined))
            }
          />
        ))}
      </div>
    </section>
  );
}
