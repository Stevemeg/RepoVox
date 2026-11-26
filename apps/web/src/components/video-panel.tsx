"use client";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { RemediationPanel } from "@/components/ui/remediation-panel";
import { SkeletonRows } from "@/components/ui/states";
import { WorkspaceContext } from "@/components/workspace/context";
import { useAction } from "@/components/workspace/use-action";
import { api, ApiError, API_BASE, type Video, type VideoJob } from "@/lib/api";
import { describeJobOutcome, toProblem, type Problem } from "@/lib/errors";
import { shortId, TERMINAL_VIDEO_STATES } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { isUuid } from "@/lib/security";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";

export type { Video, VideoJob };

const REFRESH_MS = 3000;

// Same-origin, owner-authorized routes only. Ids are validated before they enter a URL.
export function videoRoutes(jobId: string, videoId: string) {
  if (!isUuid(jobId) || !isUuid(videoId)) return null;
  const base = `${API_BASE}/video-jobs/${jobId}/videos/${videoId}`;
  return {
    video: base,
    captions: `${base}/captions`,
    download: `${base}/download`,
  };
}

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

// Every frame already shows its caption in the lower band, so the WebVTT track is loaded
// hidden: its cues are available to the page and to the player's captions menu, but the
// browser does not draw a second caption box over the burned-in one. Without `default` a
// track starts disabled and is never fetched; "hidden" fetches it without drawing it.
// The callback is module-level, so its identity is stable and React calls it only when
// the track mounts: a re-render does not undo a viewer's own captions choice.
function loadCaptionsHidden(element: HTMLTrackElement | null) {
  if (element?.track) element.track.mode = "hidden";
}

export function VideoPlayer({ jobId, video }: { jobId: string; video: Video }) {
  const [failed, setFailed] = useState(false);
  const routes = videoRoutes(jobId, video.id);
  const seconds = video.metadata.duration_seconds ?? video.metadata.media?.duration_seconds;
  if (!routes || failed)
    return (
      <p role="status" className="notice" data-tone="neutral">
        {video.title}: this video is not available. It may have expired.
      </p>
    );
  return (
    <figure className="video-item">
      <figcaption>
        <strong>{video.title}</strong>{" "}
        <span>
          {video.category === "architecture" ? "Architecture explainer" : "Repository walkthrough"}
          {seconds ? ` · ${Math.round(seconds)} s` : ""}
        </span>
      </figcaption>
      <video
        className="video-player"
        controls
        preload="metadata"
        aria-label={video.title}
        onError={() => setFailed(true)}
      >
        <source src={routes.video} type="video/mp4" />
        <track
          ref={loadCaptionsHidden}
          kind="captions"
          src={routes.captions}
          srcLang="en"
          label="English"
        />
      </video>
      <div className="actions">
        <a className="button" href={routes.download} download>
          Download MP4
        </a>
      </div>
    </figure>
  );
}

function currentStage(job: VideoJob): string {
  return (
    job.stages.find((stage) => ["ready", "running", "retry_wait"].includes(stage.state))
      ?.stage_key ?? "starting"
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
        {jobs.map((job) => {
          const outcome = describeJobOutcome(job.error_code);
          return (
            <article
              key={job.id}
              className="video-job"
              aria-label={`Video job ${shortId(job.id)}`}
            >
              <h3>
                Video job <code className="sha">{shortId(job.id)}</code>
                <span aria-hidden="true">·</span>
                {/* Raw state text: the video E2E reads it from this heading (M3 restyles it). */}
                <Badge state={job.state} />
              </h3>
              {job.commit_sha && (
                <p>
                  {job.repository} · pinned commit <code className="sha">{job.commit_sha}</code>
                </p>
              )}
              {!TERMINAL_VIDEO_STATES.includes(job.state) && (
                <>
                  <p role="status">
                    {job.state === "awaiting_analysis"
                      ? "Waiting for verified static analysis to finish."
                      : `Working: ${currentStage(job)}.`}
                  </p>
                  <div className="actions">
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() =>
                        void action
                          .run(() => api(`/video-jobs/${job.id}/cancel`, { method: "POST" }))
                          .then((ok) => (ok ? load() : undefined))
                      }
                    >
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
              {job.state === "failed" && <RemediationPanel code={job.error_code} />}
              {job.state === "succeeded" && (
                <p data-architecture={job.architecture ?? "unknown"}>{architectureNote(job)}</p>
              )}
              {job.videos.map((video) => (
                <VideoPlayer key={video.id} jobId={job.id} video={video} />
              ))}
            </article>
          );
        })}
      </div>
    </section>
  );
}
