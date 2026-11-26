"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Clapperboard,
  Folder,
  Info,
  Sparkles,
  Workflow,
} from "lucide-react";
import { EmptyState, SkeletonRows } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import type { Account } from "@/lib/api";
import {
  historyItems,
  isActiveState,
  isCompletedAnalysis,
  publishedVideos,
} from "@/lib/job-status";
import { useWorkspace } from "./context";
import { NewProjectButton } from "./create-project";
import { VideoLoadFailures } from "./jobs";
import { HistoryList, JOB_LIST_LIMIT, ProjectGrid } from "./records";
import { useVideoJobs } from "./use-video-jobs";

/**
 * One metric. `value` null means "not known yet": a skeleton is shown instead of a number,
 * so a count is never displayed before the data behind it has loaded.
 */
function Stat({
  label,
  value,
  icon,
  note,
}: {
  label: string;
  value: number | string | null;
  icon: ReactNode;
  note: string;
}) {
  return (
    <div className="stat" aria-busy={value === null}>
      <div className="stat-label">
        <span>{label}</span>
        {icon}
      </div>
      {value === null ? (
        <span className="skeleton stat-skeleton" aria-hidden="true" />
      ) : (
        <strong className="stat-value">{value}</strong>
      )}
      <small className="stat-note">{value === null ? "Loading…" : note}</small>
    </div>
  );
}

/** What this environment can actually do, read from the session's feature flags. */
export function CapabilityCallout({ account }: { account: Account }) {
  if (account.video_enabled)
    return (
      <div className="callout overview-callout">
        <Sparkles size={22} aria-hidden="true" />
        <div>
          <strong>Create narrated videos from a project</strong>
          <p>
            Open a project and start a video job. RepoVox reads one pinned commit of the
            public repository as data, never runs it, and publishes a walkthrough plus any
            architecture explainers the source evidence supports.
          </p>
        </div>
        <Link className="button button-primary" href="/projects">
          Go to your projects <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    );
  return (
    <div className="callout overview-callout" data-tone="neutral">
      <Info size={22} aria-hidden="true" />
      <div>
        <strong>Narrated videos are not enabled in this environment</strong>
        <p>
          {account.analysis_enabled
            ? "Repository analysis is available from each project page."
            : "Repository analysis is not enabled here either. Projects store repository locators only."}
        </p>
      </div>
    </div>
  );
}

export function OverviewView() {
  const { account, projects, jobs, loading } = useWorkspace();
  const videos = useVideoJobs(
    projects,
    account.video_enabled,
    jobs.map((job) => job.id).join(","),
  );
  const now = Date.now();
  const firstName = account.display_name.split(" ")[0] || account.display_name;

  // Every number below is computed from API responses only; none is assumed.
  const videosKnown = !videos.enabled || videos.settled;
  const partial = videos.failures.length > 0;
  const activeAnalyses = jobs.filter((job) => isActiveState(job.state)).length;
  const activeVideos = videos.jobs.filter((job) => isActiveState(job.state)).length;
  const completed = jobs.filter(isCompletedAnalysis).length;
  const published = publishedVideos(videos.jobs, now).length;
  const capped = jobs.length >= JOB_LIST_LIMIT;
  const recent = historyItems(jobs, videos.jobs, projects, now).slice(0, 5);

  return (
    <>
      <PageHeader
        eyebrow="Your workspace at a glance"
        title="Overview"
        description={`Welcome back, ${firstName}. Let's bring a little clarity to your code.`}
      />
      <div className="stat-grid">
        <Stat
          label="Projects"
          value={loading ? null : projects.length}
          icon={<Folder size={18} aria-hidden="true" />}
          note="Repository locators in your workspace"
        />
        <Stat
          label="Active jobs"
          value={loading || !videosKnown ? null : activeAnalyses + activeVideos}
          icon={<Workflow size={18} aria-hidden="true" />}
          note={
            videos.enabled
              ? partial
                ? "Queued or running. Some projects' video jobs could not be loaded"
                : "Analyses, fixtures and video jobs queued or running"
              : "Analyses and fixtures queued or running"
          }
        />
        <Stat
          label="Completed analyses"
          value={loading ? null : completed}
          icon={<CheckCircle2 size={18} aria-hidden="true" />}
          note={
            capped
              ? `Verified static analyses among your ${JOB_LIST_LIMIT} most recent jobs`
              : "Verified static analyses that finished Stages 1–9"
          }
        />
        <Stat
          label="Published videos"
          value={videos.enabled ? (videosKnown ? published : null) : "—"}
          icon={<Clapperboard size={18} aria-hidden="true" />}
          note={
            !videos.enabled
              ? "Video generation is off here, so there is nothing to count"
              : partial
                ? `Unexpired videos from ${videos.projectCount - videos.failures.length} of ${videos.projectCount} projects`
                : "Unexpired videos you can watch or download"
          }
        />
      </div>
      <VideoLoadFailures videos={videos} />
      <CapabilityCallout account={account} />
      <section className="panel" aria-labelledby="overview-projects" aria-busy={loading}>
        <div className="panel-header">
          <h2 id="overview-projects">
            Your projects <span className="panel-count">{projects.length}</span>
          </h2>
          <Link className="panel-link" href="/projects">
            View all <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        {loading ? (
          <SkeletonRows />
        ) : projects.length ? (
          <div className="panel-body">
            <ProjectGrid projects={projects.slice(0, 3)} jobs={jobs} />
          </div>
        ) : (
          <EmptyState
            title="No projects yet"
            description="Add a public GitHub repository to start building its story."
            action={<NewProjectButton />}
          />
        )}
      </section>
      <section
        className="panel"
        aria-labelledby="overview-activity"
        aria-busy={loading || !videosKnown}
      >
        <div className="panel-header">
          <h2 id="overview-activity">Recent activity</h2>
          <Link className="panel-link" href="/jobs">
            Job history <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        {loading || !videosKnown ? (
          <SkeletonRows />
        ) : recent.length ? (
          <HistoryList items={recent} />
        ) : (
          <EmptyState
            title="No jobs yet"
            description="Video jobs, repository analyses and synthetic fixtures appear here once you start one from a project."
          />
        )}
      </section>
    </>
  );
}
