"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Pencil, Trash2 } from "lucide-react";
import { VideoJobs } from "@/components/video-panel";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ExternalLink } from "@/components/ui/external-link";
import { PageHeader } from "@/components/ui/page-header";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { RemediationPanel } from "@/components/ui/remediation-panel";
import { SkeletonRows } from "@/components/ui/states";
import {
  api,
  ApiError,
  type Job,
  type Project,
  type ProjectDeletion,
  type VideoJob,
} from "@/lib/api";
import { toProblem, type Problem } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { isActiveState, isCompletedAnalysis, projectActivity } from "@/lib/job-status";
import { isUuid, safeGitHubRepoUrl } from "@/lib/security";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";
import { useWorkspace } from "./context";
import { JobList, repositoryLabel } from "./records";
import { RenameProjectDialog } from "./rename-project";
import { useAction } from "./use-action";

const REFRESH_MS = 5000;

/** Rotate only after success, or after the API says the key was used for other details. */
function settleKey(ok: boolean, key: { rotate: () => void }, error?: unknown) {
  if (ok || (error instanceof ApiError && error.code === "idempotency_conflict")) key.rotate();
}

/**
 * The banner shown on Projects after `DELETE /projects/{id}` answers 202. It states exactly
 * what the response says: access is revoked now, and cleanup is pending, not finished.
 */
export function deletionNotice(title: string, result: ProjectDeletion | undefined) {
  const revoked = result?.access_revoked === true;
  const pending = result?.cleanup === "pending";
  return {
    path: "/projects",
    title: "Project deleted",
    message: [
      `“${title}” was removed from your workspace.`,
      revoked
        ? "Access to the project and its jobs was revoked immediately."
        : "RepoVox accepted the deletion request.",
      pending
        ? "Its stored records and artifacts are being cleaned up in the background, so removal from storage is not instant."
        : "Cleanup of its stored records and artifacts is handled in the background.",
    ].join(" "),
    reference: result && isUuid(result.deletion_id) ? `deletion ${result.deletion_id}` : undefined,
  };
}

function AnalysisAction({ project, onStarted }: { project: Project; onStarted: () => void }) {
  const { refresh } = useWorkspace();
  const key = useIdempotencyKey();
  const action = useAction("analysis");
  const [acknowledged, setAcknowledged] = useState(false);
  async function start() {
    let failure: unknown;
    const ok = await action.run(() =>
      api(`/development/projects/${project.id}/analysis-jobs`, {
        method: "POST",
        idempotencyKey: key.current(),
        body: JSON.stringify({ processing_acknowledged: true }),
      }).catch((cause: unknown) => {
        failure = cause;
        throw cause;
      }),
    );
    settleKey(ok, key, failure);
    if (ok) {
      onStarted();
      await refresh();
    }
  }
  return (
    <div className="panel-body">
      <h3 className="section-title">Repository analysis</h3>
      <p>
        Downloads one public GitHub snapshot into private local storage for up to 24 hours,
        screens it for credentials, and parses it as data. Repository code is never run. No
        video is produced by this job.
      </p>
      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        I acknowledge this local source processing.
      </label>
      <div className="actions">
        <button
          type="button"
          className="button-primary"
          disabled={action.busy || !acknowledged}
          onClick={() => void start()}
        >
          {action.busy ? "Starting…" : "Analyze repository"}
        </button>
      </div>
      {action.problem && (
        <>
          <ProblemNotice problem={action.problem} />
          <RemediationPanel code={action.problem.code} context="request" compact />
        </>
      )}
    </div>
  );
}

function FixtureAction({ project, onStarted }: { project: Project; onStarted: () => void }) {
  const { refresh } = useWorkspace();
  const key = useIdempotencyKey();
  const action = useAction("fixture");
  async function start() {
    let failure: unknown;
    const ok = await action.run(() =>
      api(`/development/projects/${project.id}/fixture-jobs`, {
        method: "POST",
        idempotencyKey: key.current(),
        body: JSON.stringify({ fixture: "normal" }),
      }).catch((cause: unknown) => {
        failure = cause;
        throw cause;
      }),
    );
    settleKey(ok, key, failure);
    if (ok) {
      onStarted();
      await refresh();
    }
  }
  return (
    <div className="panel-body">
      <h3 className="section-title">Synthetic fixture</h3>
      <p>
        Runs a trusted development fixture through the durable job pipeline. It reads no
        repository and produces no video.
      </p>
      <div className="actions">
        <button type="button" disabled={action.busy} onClick={() => void start()}>
          {action.busy ? "Starting…" : "Run synthetic fixture"}
        </button>
      </div>
      {action.problem && (
        <>
          <ProblemNotice problem={action.problem} />
          <RemediationPanel code={action.problem.code} context="request" compact />
        </>
      )}
    </div>
  );
}

/** Everything this page loaded for one project id. A view for another id is ignored. */
type Loaded = {
  projectId: string;
  project: Project | null;
  /** The API answered 404: deleted, never existed, or another account's. */
  missing: boolean;
  problem: Problem | null;
  /** This project's analysis and fixture jobs; null until first loaded. */
  jobs: Job[] | null;
  jobsProblem: Problem | null;
};
const empty = (projectId: string): Loaded => ({
  projectId,
  project: null,
  missing: false,
  problem: null,
  jobs: null,
  jobsProblem: null,
});

export function ProjectDetailView({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { account, handleUnauthorized, refresh, showFlash } = useWorkspace();
  const remove = useAction("delete-project");
  const [loaded, setLoaded] = useState<Loaded>(() => empty(projectId));
  const [videoJobs, setVideoJobs] = useState<{ projectId: string; jobs: VideoJob[] | null }>();
  const [confirming, setConfirming] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renamed, setRenamed] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);
  const view = loaded.projectId === projectId ? loaded : empty(projectId);

  /** The project itself and its own jobs, straight from the API, never from a cache. */
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const [project, jobs] = await Promise.allSettled([
        api<Project>(`/projects/${projectId}`, { signal }),
        api<Job[]>(`/projects/${projectId}/jobs`, { signal }),
      ]);
      if (signal?.aborted) return;
      for (const result of [project, jobs])
        if (result.status === "rejected" && handleUnauthorized(result.reason)) return;
      setLoaded((previous) => {
        const base = previous.projectId === projectId ? previous : empty(projectId);
        if (project.status === "rejected") {
          const cause = project.reason;
          if (cause instanceof ApiError && cause.status === 404)
            return { ...empty(projectId), missing: true };
          return { ...base, problem: toProblem(cause) };
        }
        return {
          projectId,
          project: project.value,
          missing: false,
          problem: null,
          jobs: jobs.status === "fulfilled" ? jobs.value : base.jobs,
          jobsProblem: jobs.status === "rejected" ? toProblem(jobs.reason) : null,
        };
      });
    },
    [projectId, handleUnauthorized],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const projectJobs = view.jobs;
  const videos = videoJobs?.projectId === projectId ? videoJobs.jobs : null;
  const active =
    !!projectJobs?.some((job) => isActiveState(job.state)) ||
    !!videos?.some((job) => isActiveState(job.state));
  // A video job also admits an analysis job, so refreshing while either runs shows both.
  useVisibilityPolling(() => load(), REFRESH_MS, active && !deleted);
  const reportVideoJobs = useCallback(
    (jobs: VideoJob[] | null) => setVideoJobs({ projectId, jobs }),
    [projectId],
  );

  if (deleted)
    return (
      <p role="status" className="notice" data-tone="neutral">
        Project deleted. Returning to your projects…
      </p>
    );
  if (view.missing)
    return (
      <section className="panel">
        <div className="panel-body">
          <h1>Project unavailable</h1>
          <p>
            This project is not in your workspace. It may have been deleted, or it belongs to
            another account.
          </p>
          <Link href="/projects">Back to your projects</Link>
        </div>
      </section>
    );
  const project = view.project;
  if (!project)
    return view.problem ? (
      <>
        <PageHeader eyebrow="Project" title="Project could not be loaded" />
        <ProblemNotice problem={view.problem} onRetry={() => void load()} />
        <Link href="/projects">Back to your projects</Link>
      </>
    ) : (
      <section className="panel" aria-busy="true">
        <SkeletonRows />
      </section>
    );

  const repository = safeGitHubRepoUrl(project.repository_url);
  const videoEnabled = account.video_enabled;
  const activity =
    projectJobs && (!videoEnabled || videoJobs?.projectId === projectId)
      ? projectActivity(projectJobs, videoEnabled ? videos : null, Date.now())
      : null;
  const latestAnalysis = projectJobs?.find(isCompletedAnalysis);
  const startedJob = () => void load();

  async function confirmDelete() {
    if (!project) return;
    let result: ProjectDeletion | undefined;
    const ok = await remove.run(async () => {
      result = await api<ProjectDeletion>(`/projects/${project.id}`, { method: "DELETE" });
    });
    if (!ok) return;
    setConfirming(false);
    setDeleted(true);
    showFlash(deletionNotice(project.title, result));
    router.push("/projects");
    void refresh();
  }

  return (
    <>
      <PageHeader
        eyebrow="Project"
        title={project.title}
        description={`Added ${formatDate(project.created_at)}`}
        actions={
          <>
            <button type="button" onClick={() => setRenaming(true)}>
              <Pencil size={16} aria-hidden="true" /> Rename project
            </button>
            <button
              type="button"
              className="button-danger-outline"
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={16} aria-hidden="true" /> Delete project
            </button>
          </>
        }
      />
      {renamed && (
        <p role="status" className="notice" data-tone="success">
          Project renamed to “{renamed}”.
        </p>
      )}
      {view.problem && <ProblemNotice problem={view.problem} onRetry={() => void load()} />}
      <section className="panel" aria-labelledby="project-repository">
        <div className="panel-header">
          <h2 id="project-repository">Repository</h2>
          {activity ? (
            <Badge state={activity.key} label={activity.label} tone={activity.tone} />
          ) : (
            <span className="panel-meta" role="status">
              Checking project activity…
            </span>
          )}
        </div>
        <div className="panel-body">
          {activity && (
            <p className="project-activity" data-activity={activity.key}>
              {activity.description}
              {latestAnalysis && activity.key !== "analyzing" && (
                <>
                  {" "}
                  <Link href={`/jobs/${encodeURIComponent(latestAnalysis.id)}`}>
                    Open the latest verified analysis
                    <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                </>
              )}
            </p>
          )}
          <dl className="definition-list">
            <dt>Locator</dt>
            <dd>
              {repository ? (
                <ExternalLink href={repository}>{repositoryLabel(repository)}</ExternalLink>
              ) : (
                <span className="mono">{project.repository_url}</span>
              )}
            </dd>
            <dt>API record status</dt>
            <dd>
              <code>{project.status}</code>
            </dd>
          </dl>
          <p className="field-hint">
            RepoVox does not verify who owns the repository. A job reads one pinned public
            commit as data and never runs repository code.
          </p>
        </div>
      </section>
      {(account.analysis_enabled || account.fixtures_enabled) && (
        <section className="panel" aria-label="Start a job">
          {account.analysis_enabled && (
            <AnalysisAction project={project} onStarted={startedJob} />
          )}
          {account.fixtures_enabled && <FixtureAction project={project} onStarted={startedJob} />}
        </section>
      )}
      {videoEnabled && <VideoJobs projectId={project.id} onJobs={reportVideoJobs} />}
      <section className="panel" aria-labelledby="project-jobs" aria-busy={projectJobs === null}>
        <div className="panel-header">
          <h2 id="project-jobs">Project jobs</h2>
          <span className="panel-meta">Analyses and fixtures</span>
        </div>
        {view.jobsProblem && (
          <div className="panel-body">
            <ProblemNotice problem={view.jobsProblem} onRetry={() => void load()} />
          </div>
        )}
        {projectJobs === null ? (
          !view.jobsProblem && <SkeletonRows />
        ) : (
          <JobList
            jobs={projectJobs}
            emptyDescription="Analyses and synthetic fixtures you start for this project appear here."
          />
        )}
      </section>
      {renaming && (
        <RenameProjectDialog
          project={project}
          onClose={() => setRenaming(false)}
          onRenamed={(updated) => {
            setLoaded((previous) =>
              previous.projectId === projectId ? { ...previous, project: updated } : previous,
            );
            setRenamed(updated.title);
            setRenaming(false);
            void refresh();
          }}
        />
      )}
      {confirming && (
        <ConfirmDialog
          title="Delete this project?"
          description={
            <p>
              “{project.title}” will be removed from your workspace and access to its jobs
              revoked immediately. Stored records are cleaned up afterwards in the background.
              This cannot be undone.
            </p>
          }
          confirmLabel="Delete project"
          busyLabel="Deleting…"
          busy={remove.busy}
          problem={remove.problem}
          onConfirm={() => void confirmDelete()}
          onCancel={() => {
            setConfirming(false);
            remove.clear();
          }}
        />
      )}
    </>
  );
}
