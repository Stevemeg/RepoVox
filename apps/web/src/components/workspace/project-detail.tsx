"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { VideoJobs } from "@/components/video-panel";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ExternalLink } from "@/components/ui/external-link";
import { PageHeader } from "@/components/ui/page-header";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { SkeletonRows } from "@/components/ui/states";
import { api, ApiError, type Project } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { safeGitHubRepoUrl } from "@/lib/security";
import { useWorkspace } from "./context";
import { JobList, repositoryLabel } from "./records";
import { useAction } from "./use-action";

/** Rotate only after success, or after the API says the key was used for other details. */
function settleKey(ok: boolean, key: { rotate: () => void }, error?: unknown) {
  if (ok || (error instanceof ApiError && error.code === "idempotency_conflict")) key.rotate();
}

function AnalysisAction({ project }: { project: Project }) {
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
    if (ok) await refresh();
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
      {action.problem && <ProblemNotice problem={action.problem} />}
    </div>
  );
}

function FixtureAction({ project }: { project: Project }) {
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
    if (ok) await refresh();
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
      {action.problem && <ProblemNotice problem={action.problem} />}
    </div>
  );
}

export function ProjectDetailView({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { account, projects, jobs, loading, refresh } = useWorkspace();
  const remove = useAction("delete-project");
  const [confirming, setConfirming] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const project = projects.find((item) => item.id === projectId);

  if (deleted)
    return (
      <p role="status" className="notice" data-tone="neutral">
        Project deleted. Returning to your projects…
      </p>
    );
  if (!project)
    return loading ? (
      <section className="panel" aria-busy="true">
        <SkeletonRows />
      </section>
    ) : (
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

  const repository = safeGitHubRepoUrl(project.repository_url);
  const projectJobs = jobs.filter((job) => job.project_id === project.id);

  async function confirmDelete() {
    if (!project) return;
    const ok = await remove.run(() => api(`/projects/${project.id}`, { method: "DELETE" }));
    if (!ok) return;
    setConfirming(false);
    setDeleted(true);
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
          <button
            type="button"
            className="button-danger-outline"
            onClick={() => setConfirming(true)}
          >
            <Trash2 size={16} aria-hidden="true" /> Delete project
          </button>
        }
      />
      <section className="panel" aria-labelledby="project-repository">
        <div className="panel-header">
          <h2 id="project-repository">Repository</h2>
          <Badge state={project.status} />
        </div>
        <div className="panel-body">
          <dl className="definition-list">
            <dt>Locator</dt>
            <dd>
              {repository ? (
                <ExternalLink href={repository}>{repositoryLabel(repository)}</ExternalLink>
              ) : (
                <span className="mono">{project.repository_url}</span>
              )}
            </dd>
          </dl>
          <p className="field-hint">
            RepoVox stores this locator and does not verify who owns the repository. A job
            reads one pinned public commit as data and never runs repository code.
          </p>
        </div>
      </section>
      {(account.analysis_enabled || account.fixtures_enabled) && (
        <section className="panel" aria-label="Start a job">
          {account.analysis_enabled && <AnalysisAction project={project} />}
          {account.fixtures_enabled && <FixtureAction project={project} />}
        </section>
      )}
      {account.video_enabled && <VideoJobs projectId={project.id} />}
      <section className="panel" aria-labelledby="project-jobs">
        <div className="panel-header">
          <h2 id="project-jobs">Project jobs</h2>
          <span className="panel-meta">Analyses and fixtures</span>
        </div>
        <JobList
          jobs={projectJobs}
          emptyDescription="Analyses and synthetic fixtures you start for this project appear here."
        />
      </section>
      {confirming && (
        <ConfirmDialog
          title="Delete this project?"
          description={
            <p>
              “{project.title}” will be removed from your workspace and access to its jobs
              revoked immediately. Stored records are cleaned up afterwards. This cannot be
              undone.
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
