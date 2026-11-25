"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Clock3, Folder, Info, Sparkles, Workflow } from "lucide-react";
import { EmptyState, SkeletonRows } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import type { Account } from "@/lib/api";
import { ACTIVE_JOB_STATES } from "@/lib/format";
import { useWorkspace } from "./context";
import { NewProjectButton } from "./create-project";
import { JobList, ProjectGrid } from "./records";

function Stat({
  label,
  value,
  icon,
  note,
}: {
  label: string;
  value: number;
  icon: ReactNode;
  note: string;
}) {
  return (
    <div className="stat">
      <div className="stat-label">
        <span>{label}</span>
        {icon}
      </div>
      <strong className="stat-value">{value}</strong>
      <small className="stat-note">{note}</small>
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
  const active = jobs.filter((job) => ACTIVE_JOB_STATES.includes(job.state)).length;
  const firstName = account.display_name.split(" ")[0] || account.display_name;
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
          value={projects.length}
          icon={<Folder size={18} aria-hidden="true" />}
          note="Repository locators in your workspace"
        />
        <Stat
          label="Active jobs"
          value={active}
          icon={<Workflow size={18} aria-hidden="true" />}
          note="Queued, running or waiting to retry"
        />
        <Stat
          label="Job history"
          value={jobs.length}
          icon={<Clock3 size={18} aria-hidden="true" />}
          note="Repository analyses and synthetic fixtures"
        />
      </div>
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
            <ProjectGrid projects={projects.slice(0, 3)} />
          </div>
        ) : (
          <EmptyState
            title="No projects yet"
            description="Add a public GitHub repository to start building its story."
            action={<NewProjectButton />}
          />
        )}
      </section>
      <section className="panel" aria-labelledby="overview-activity" aria-busy={loading}>
        <div className="panel-header">
          <h2 id="overview-activity">Recent activity</h2>
          <Link className="panel-link" href="/jobs">
            Job history <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        {loading ? <SkeletonRows /> : <JobList jobs={jobs.slice(0, 5)} />}
      </section>
    </>
  );
}
