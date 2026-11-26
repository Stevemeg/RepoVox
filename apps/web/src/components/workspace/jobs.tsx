"use client";
import { useId, useState } from "react";
import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, SkeletonRows } from "@/components/ui/states";
import {
  filterHistory,
  historyItems,
  type StatusFilter,
  type TypeFilter,
} from "@/lib/job-status";
import { useWorkspace } from "./context";
import { HistoryList, JOB_LIST_LIMIT } from "./records";
import { useVideoJobs, type VideoJobsState } from "./use-video-jobs";

/** The per-project video-job listing returns at most this many of a project's jobs. */
export const VIDEO_JOB_LIST_LIMIT = 50;

const TYPES: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "All types" },
  { value: "video", label: "Video jobs" },
  { value: "analysis", label: "Analyses" },
  { value: "fixture", label: "Fixtures" },
];
const STATUSES: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "succeeded", label: "Succeeded / complete" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

/** Which projects' video jobs are missing, with a way to try again. Never silent. */
export function VideoLoadFailures({ videos }: { videos: VideoJobsState }) {
  if (videos.failures.length === 0) return null;
  const names = videos.failures.map((failure) => `“${failure.projectTitle}”`).join(", ");
  const first = videos.failures[0].problem;
  return (
    <div className="problem" role="alert">
      <div className="problem-body">
        <p className="problem-message">
          Video jobs could not be loaded for {videos.failures.length} of {videos.projectCount}{" "}
          {videos.projectCount === 1 ? "project" : "projects"} ({names}), so they are missing
          here and video counts may be incomplete. Everything else shown is current.
        </p>
        <small className="problem-meta">
          Reference: {first.code}
          {first.requestId ? ` · request ${first.requestId}` : ""}
        </small>
      </div>
      <button type="button" onClick={() => void videos.reload()}>
        Try again
      </button>
    </div>
  );
}

export function JobsView() {
  const { account, projects, jobs, loading } = useWorkspace();
  const videos = useVideoJobs(
    projects,
    account.video_enabled,
    jobs.map((job) => job.id).join(","),
  );
  const [type, setType] = useState<TypeFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const typeId = useId();
  const statusId = useId();
  const searchId = useId();

  const items = historyItems(jobs, videos.jobs, projects, Date.now());
  const shown = filterHistory(items, { type, status, query });
  const filtered = type !== "all" || status !== "all" || query.trim() !== "";
  const perProject = new Map<string, number>();
  for (const job of videos.jobs)
    perProject.set(job.project_id, (perProject.get(job.project_id) ?? 0) + 1);
  const videoCapped = [...perProject.values()].some((count) => count >= VIDEO_JOB_LIST_LIMIT);
  const pendingVideos = videos.enabled && !videos.settled;

  return (
    <>
      <PageHeader
        eyebrow="History"
        title="Job history"
        description="Every narrated video job, repository analysis and synthetic fixture you started, newest first."
      />
      <div className="notice" data-tone="neutral">
        <Info size={16} aria-hidden="true" />
        <p>
          Synthetic fixtures exercise the job pipeline only; they do not analyze repositories
          or generate videos. An analysis that finishes Stages 1–9 with a verified result is
          recorded by the API as <code>failed</code> with the boundary code{" "}
          <code>phase2_pipeline_boundary</code>; it is shown here as Analysis complete, with
          the recorded state beside it.
          {!account.video_enabled && " Narrated videos are not enabled in this environment."}
        </p>
      </div>
      <VideoLoadFailures videos={videos} />
      <section className="panel" aria-labelledby="job-history-list" aria-busy={loading}>
        <div className="panel-header">
          <h2 id="job-history-list">All jobs</h2>
          <p className="panel-meta" role="status" aria-live="polite">
            {loading
              ? "Loading jobs…"
              : filtered
                ? `Showing ${shown.length} of ${items.length} jobs`
                : `${items.length} ${items.length === 1 ? "job" : "jobs"}`}
            {pendingVideos && " · loading video jobs…"}
          </p>
        </div>
        <form
          className="filter-bar"
          role="search"
          aria-label="Filter jobs"
          onSubmit={(event) => event.preventDefault()}
        >
          <div className="field">
            <label htmlFor={typeId}>Type</label>
            <select
              id={typeId}
              className="input"
              value={type}
              onChange={(event) => setType(event.target.value as TypeFilter)}
            >
              {TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={statusId}>Status</label>
            <select
              id={statusId}
              className="input"
              value={status}
              onChange={(event) => setStatus(event.target.value as StatusFilter)}
            >
              {STATUSES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field filter-search">
            <label htmlFor={searchId}>Search</label>
            <input
              id={searchId}
              type="search"
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Project, repository URL or commit SHA"
              maxLength={200}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          {filtered && (
            <button
              type="button"
              className="button-ghost filter-clear"
              onClick={() => {
                setType("all");
                setStatus("all");
                setQuery("");
              }}
            >
              Clear filters
            </button>
          )}
        </form>
        {loading ? (
          <SkeletonRows rows={5} />
        ) : shown.length ? (
          <HistoryList items={shown} />
        ) : items.length && filtered ? (
          <EmptyState
            title="No jobs match these filters"
            description="Change the type, status or search text, or clear the filters to see every job."
          />
        ) : (
          !pendingVideos && (
            <EmptyState
              title="No jobs yet"
              description="Video jobs, repository analyses and synthetic fixtures appear here once you start one from a project."
            />
          )
        )}
        {pendingVideos && <SkeletonRows rows={2} />}
      </section>
      {(jobs.length >= JOB_LIST_LIMIT || videoCapped) && (
        <p className="field-hint list-limits">
          {jobs.length >= JOB_LIST_LIMIT &&
            `Only your ${JOB_LIST_LIMIT} most recent analysis and fixture jobs are listed. `}
          {videoCapped &&
            `Only the ${VIDEO_JOB_LIST_LIMIT} most recent video jobs of each project are listed.`}
        </p>
      )}
    </>
  );
}
