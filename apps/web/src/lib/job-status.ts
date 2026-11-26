/*
 * One place that turns a job's raw backend state into what a person should see.
 *
 * Analysis and fixture jobs end a normal run at a pipeline boundary by being recorded as
 * `failed` with a fixed boundary code:
 *  - `phase2_pipeline_boundary`: an analysis finished Stages 1-9 and its verified result is
 *    available;
 *  - `phase1_fixture_boundary`: a synthetic fixture finished its demonstration.
 * That is the expected end, so it is shown as "Analysis complete" / "Fixture complete" with
 * a positive tone, never as a red failure. The raw `state` and `error_code` stay on every
 * status so views can still show them as technical metadata; nothing is hidden.
 */
import type { Job, Project, Video, VideoJob } from "./types";

/** The subset of badge tones a job status uses. */
export type StatusTone = "neutral" | "running" | "succeeded" | "failed" | "warning";
export type JobKind = "analysis" | "fixture" | "video";
export type StatusGroup = "active" | "succeeded" | "failed" | "cancelled" | "other";

export type JobStatus = {
  group: StatusGroup;
  label: string;
  tone: StatusTone;
  /** True when a `failed` record is really the normal end at a pipeline boundary. */
  boundary: boolean;
  /** Exactly what the API sent, for technical details. */
  rawState: string;
  errorCode: string | null;
};

export const ANALYSIS_BOUNDARY = "phase2_pipeline_boundary";
export const FIXTURE_BOUNDARY = "phase1_fixture_boundary";

const ACTIVE = new Set(["queued", "running", "retry_wait", "awaiting_analysis"]);
const STATES: Record<string, { label: string; tone: StatusTone; group: StatusGroup }> = {
  queued: { label: "Queued", tone: "warning", group: "active" },
  running: { label: "Running", tone: "running", group: "active" },
  retry_wait: { label: "Waiting to retry", tone: "warning", group: "active" },
  awaiting_analysis: { label: "Awaiting analysis", tone: "warning", group: "active" },
  succeeded: { label: "Succeeded", tone: "succeeded", group: "succeeded" },
  failed: { label: "Failed", tone: "failed", group: "failed" },
  cancelled: { label: "Cancelled", tone: "neutral", group: "cancelled" },
};

export const isActiveState = (state: string) => ACTIVE.has(state);

export const jobKind = (job: Pick<Job, "synthetic">): JobKind =>
  job.synthetic ? "fixture" : "analysis";

function fromState(state: string, errorCode: string | null): JobStatus {
  const known = STATES[state];
  return {
    group: known?.group ?? "other",
    label: known?.label ?? state.replaceAll("_", " "),
    tone: known?.tone ?? "neutral",
    boundary: false,
    rawState: state,
    errorCode,
  };
}

/**
 * The boundary an analysis or fixture record ended at, if any. Strict per kind: a fixture
 * code on an analysis (or the reverse) is not treated as a normal end.
 */
export function boundaryOf(
  state: string,
  errorCode: string | null | undefined,
  synthetic: boolean,
): "analysis" | "fixture" | null {
  if (state !== "failed") return null;
  if (!synthetic && errorCode === ANALYSIS_BOUNDARY) return "analysis";
  if (synthetic && errorCode === FIXTURE_BOUNDARY) return "fixture";
  return null;
}

/** Status of an analysis or fixture job (or one of its history entries). */
export function jobStatus(
  job: Pick<Job, "state" | "error_code" | "synthetic">,
): JobStatus {
  const errorCode = job.error_code ?? null;
  const boundary = boundaryOf(job.state, errorCode, job.synthetic);
  if (boundary)
    return {
      group: "succeeded",
      label: boundary === "analysis" ? "Analysis complete" : "Fixture complete",
      tone: "succeeded",
      boundary: true,
      rawState: job.state,
      errorCode,
    };
  return fromState(job.state, errorCode);
}

export function videoJobStatus(job: Pick<VideoJob, "state" | "error_code">): JobStatus {
  return fromState(job.state, job.error_code ?? null);
}

/** True when a non-synthetic job finished with a verified analysis available. */
export const isCompletedAnalysis = (job: Pick<Job, "state" | "error_code" | "synthetic">) =>
  boundaryOf(job.state, job.error_code, job.synthetic) === "analysis" ||
  (!job.synthetic && job.state === "succeeded");

/* Published videos ------------------------------------------------------- */

const expiry = (video: Pick<Video, "expires_at">) => Date.parse(video.expires_at);

/** A video is published when its job succeeded and it has not yet expired. */
export function publishedVideos(jobs: readonly VideoJob[], now: number): Video[] {
  return jobs
    .filter((job) => job.state === "succeeded")
    .flatMap((job) => job.videos)
    .filter((video) => {
      const expires = expiry(video);
      return !Number.isNaN(expires) && expires > now;
    });
}

/* Unified history -------------------------------------------------------- */

export type HistoryItem = {
  kind: JobKind;
  id: string;
  projectId: string;
  projectTitle: string;
  repositoryUrl: string | null;
  commitSha: string | null;
  createdAt: string;
  status: JobStatus;
  /** Published, unexpired videos (video jobs only). */
  videoCount: number;
};

const time = (value: string) => {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
};

/** Analysis, fixture and video jobs as one list, newest first (ties broken by id). */
export function historyItems(
  jobs: readonly Job[],
  videoJobs: readonly VideoJob[],
  projects: readonly Project[],
  now: number,
): HistoryItem[] {
  const byId = new Map(projects.map((project) => [project.id, project]));
  const items: HistoryItem[] = [
    ...jobs.map((job) => ({
      kind: jobKind(job),
      id: job.id,
      projectId: job.project_id,
      projectTitle: job.project_title || byId.get(job.project_id)?.title || "Untitled project",
      repositoryUrl: job.repository_url ?? byId.get(job.project_id)?.repository_url ?? null,
      commitSha: job.commit_sha ?? null,
      createdAt: job.created_at,
      status: jobStatus(job),
      videoCount: 0,
    })),
    ...videoJobs.map((job) => ({
      kind: "video" as const,
      id: job.id,
      projectId: job.project_id,
      projectTitle: byId.get(job.project_id)?.title || "Untitled project",
      repositoryUrl: byId.get(job.project_id)?.repository_url ?? null,
      commitSha: job.commit_sha,
      createdAt: job.created_at,
      status: videoJobStatus(job),
      videoCount: publishedVideos([job], now).length,
    })),
  ];
  return items.sort(
    (a, b) => time(b.createdAt) - time(a.createdAt) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
}

export type TypeFilter = "all" | JobKind;
export type StatusFilter = "all" | Exclude<StatusGroup, "other">;

/**
 * Client-side filter over plain text. The query is matched as a case-insensitive substring
 * of the project title, repository URL and commit SHA; it is never a pattern.
 */
export function filterHistory(
  items: readonly HistoryItem[],
  { type, status, query }: { type: TypeFilter; status: StatusFilter; query: string },
): HistoryItem[] {
  const needle = query.trim().toLowerCase();
  return items.filter(
    (item) =>
      (type === "all" || item.kind === type) &&
      (status === "all" || item.status.group === status) &&
      (!needle ||
        [item.projectTitle, item.repositoryUrl ?? "", item.commitSha ?? ""].some((field) =>
          field.toLowerCase().includes(needle),
        )),
  );
}

/* Project activity ------------------------------------------------------- */

export type ProjectActivity = {
  key:
    | "new"
    | "rendering"
    | "analyzing"
    | "fixture"
    | "published"
    | "analyzed"
    | "fixtures-only"
    | "stopped"
    | "idle";
  label: string;
  tone: StatusTone;
  description: string;
};

/**
 * What has actually happened to a project, from its own jobs. `videoJobs` is null when
 * video jobs are not available (not enabled, or not loaded); every video job also admits
 * an analysis job, so a project with no analysis or fixture job has never been read.
 */
export function projectActivity(
  jobs: readonly Job[],
  videoJobs: readonly VideoJob[] | null,
  now: number,
): ProjectActivity {
  const videos = videoJobs ?? [];
  if (videos.some((job) => isActiveState(job.state)))
    return {
      key: "rendering",
      label: "Creating videos",
      tone: "running",
      description:
        "A video job is in progress. It reads one pinned commit as data; repository code is never run.",
    };
  if (jobs.some((job) => !job.synthetic && isActiveState(job.state)))
    return {
      key: "analyzing",
      label: "Analysis in progress",
      tone: "running",
      description:
        "A static analysis of one pinned commit is running. Repository code is never run.",
    };
  if (jobs.some((job) => job.synthetic && isActiveState(job.state)))
    return {
      key: "fixture",
      label: "Fixture running",
      tone: "running",
      description: "A synthetic fixture is running. Fixtures read no repository.",
    };
  const published = publishedVideos(videos, now).length;
  if (published > 0)
    return {
      key: "published",
      label: "Videos published",
      tone: "succeeded",
      description: `${published} published ${published === 1 ? "video is" : "videos are"} available until ${published === 1 ? "it expires" : "they expire"}.`,
    };
  if (jobs.some(isCompletedAnalysis))
    return {
      key: "analyzed",
      label: "Analysis complete",
      tone: "succeeded",
      description:
        "A verified static analysis of a pinned commit is available from the project's jobs.",
    };
  if (jobs.length === 0 && videos.length === 0)
    return {
      key: "new",
      label: "Newly registered",
      tone: "neutral",
      description:
        "No job has read this repository yet. RepoVox stores only its locator until you start an analysis or video job.",
    };
  const latest = [
    ...jobs.map((job) => ({ at: job.created_at, group: jobStatus(job).group })),
    ...videos.map((job) => ({ at: job.created_at, group: videoJobStatus(job).group })),
  ].sort((a, b) => time(b.at) - time(a.at))[0];
  if (latest?.group === "failed")
    return {
      key: "stopped",
      label: "Last job stopped",
      tone: "warning",
      description:
        "The most recent job stopped before it finished. Open it to see what happened and what to do next.",
    };
  if (jobs.length > 0 && jobs.every((job) => job.synthetic) && videos.length === 0)
    return {
      key: "fixtures-only",
      label: "Fixtures only",
      tone: "neutral",
      description:
        "Only synthetic fixtures have run here. Fixtures read no repository, so its contents have not been analyzed.",
    };
  return {
    key: "idle",
    label: "No verified analysis",
    tone: "neutral",
    description: "Jobs have run for this project, but none produced a verified analysis yet.",
  };
}
