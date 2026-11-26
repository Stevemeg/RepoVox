import Link from "next/link";
import { ChevronRight, Clapperboard, Code2, FlaskConical, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import type { Job, Project } from "@/lib/api";
import { formatDate, formatDateTime, shortId } from "@/lib/format";
import {
  jobStatus,
  projectActivity,
  type HistoryItem,
  type JobStatus,
} from "@/lib/job-status";
import { safeGitHubRepoUrl } from "@/lib/security";

/** "owner/name" for a validated locator; the raw string is shown only as inert text. */
export function repositoryLabel(url: string): string {
  const safe = safeGitHubRepoUrl(url);
  return safe ? safe.slice("https://github.com/".length) : url;
}

/** A job's meaning as a badge; the raw backend state is kept in `data-state`. */
export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge state={status.rawState} label={status.label} tone={status.tone} />;
}

/**
 * The raw record behind a boundary badge, so "Analysis complete" never hides that the API
 * recorded `failed` with a boundary code. Empty for every other status, whose badge already
 * names the raw state.
 */
export function RecordedState({ status }: { status: JobStatus }) {
  if (!status.boundary) return null;
  return (
    <span className="recorded-state">
      {" "}
      · recorded as <code>{status.rawState}</code> / <code>{status.errorCode}</code>
    </span>
  );
}

/** The job listing returns at most this many of an account's most recent jobs. */
export const JOB_LIST_LIMIT = 100;

export function ProjectCard({ project, jobs }: { project: Project; jobs?: readonly Job[] }) {
  // Cards see only analysis and fixture jobs; every video job also admits one of those.
  let activity = jobs
    ? projectActivity(
        jobs.filter((job) => job.project_id === project.id),
        null,
        0,
      )
    : null;
  // With a full listing, older jobs may exist beyond it: do not claim the project is new.
  if (activity?.key === "new" && jobs && jobs.length >= JOB_LIST_LIMIT)
    activity = { ...activity, label: "No recent jobs" };
  return (
    <Link className="project-card" href={`/projects/${encodeURIComponent(project.id)}`}>
      <div className="project-card-top">
        <span className="icon-tile" aria-hidden="true">
          <Code2 size={18} />
        </span>
        <ChevronRight size={16} aria-hidden="true" />
      </div>
      <h3>{project.title}</h3>
      <p className="project-card-repo">{repositoryLabel(project.repository_url)}</p>
      <div className="project-card-bottom">
        {activity ? (
          <Badge state={activity.key} label={activity.label} tone={activity.tone} />
        ) : (
          <span />
        )}
        <small>{formatDate(project.created_at)}</small>
      </div>
    </Link>
  );
}

export function ProjectGrid({
  projects,
  jobs,
}: {
  projects: readonly Project[];
  jobs?: readonly Job[];
}) {
  return (
    <div className="card-grid">
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} jobs={jobs} />
      ))}
    </div>
  );
}

export function JobList({
  jobs,
  emptyDescription = "Repository analyses and synthetic fixtures appear here once you start one from a project.",
}: {
  jobs: readonly Job[];
  emptyDescription?: string;
}) {
  if (jobs.length === 0) return <EmptyState title="No jobs yet" description={emptyDescription} />;
  return (
    <div className="job-list">
      {jobs.map((job) => {
        const status = jobStatus(job);
        return (
          <Link className="job-row" href={`/jobs/${encodeURIComponent(job.id)}`} key={job.id}>
            <span className="icon-tile" aria-hidden="true">
              <Workflow size={18} />
            </span>
            <div className="job-row-main">
              <strong>{job.project_title || "Untitled project"}</strong>
              <small>
                {job.synthetic ? "Synthetic" : "Static analysis"} · {shortId(job.id)} ·{" "}
                {formatDate(job.created_at)}
                <RecordedState status={status} />
              </small>
            </div>
            <StatusBadge status={status} />
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        );
      })}
    </div>
  );
}

const KIND = {
  video: { label: "Video job", icon: Clapperboard },
  analysis: { label: "Static analysis", icon: Workflow },
  fixture: { label: "Synthetic fixture", icon: FlaskConical },
} as const;

export const historyHref = (item: HistoryItem) =>
  item.kind === "video"
    ? `/projects/${encodeURIComponent(item.projectId)}#videos`
    : `/jobs/${encodeURIComponent(item.id)}`;

/** Analysis, fixture and video jobs in one list. Every value is rendered as text. */
export function HistoryList({ items }: { items: readonly HistoryItem[] }) {
  return (
    <ul className="job-list history-items">
      {items.map((item) => {
        const kind = KIND[item.kind];
        return (
          <li key={`${item.kind}-${item.id}`}>
            <Link className="job-row" href={historyHref(item)} data-kind={item.kind}>
              <span className="icon-tile" aria-hidden="true">
                <kind.icon size={18} />
              </span>
              <div className="job-row-main">
                <strong>{item.projectTitle}</strong>
                <small>
                  {kind.label} · {shortId(item.id)} · {formatDateTime(item.createdAt)}
                  {item.repositoryUrl && <> · {repositoryLabel(item.repositoryUrl)}</>}
                  {item.commitSha && (
                    <>
                      {" "}
                      · <code className="sha">{item.commitSha.slice(0, 12)}</code>
                    </>
                  )}
                  {item.kind === "video" && item.status.group === "succeeded" && (
                    <>
                      {" "}
                      ·{" "}
                      {item.videoCount === 0
                        ? "videos expired"
                        : `${item.videoCount} ${item.videoCount === 1 ? "video" : "videos"} published`}
                    </>
                  )}
                  <RecordedState status={item.status} />
                </small>
              </div>
              <StatusBadge status={item.status} />
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
