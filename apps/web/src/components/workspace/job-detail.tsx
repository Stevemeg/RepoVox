"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AnalysisPanel } from "@/components/analysis-panel";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/external-link";
import { PageHeader } from "@/components/ui/page-header";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { RemediationPanel } from "@/components/ui/remediation-panel";
import { SkeletonRows } from "@/components/ui/states";
import { linkAbort } from "@/lib/abort";
import { api, ApiError, type Job } from "@/lib/api";
import { describeJobOutcome, toProblem, type Problem } from "@/lib/errors";
import { ACTIVE_JOB_STATES, formatDate, formatDateTime, humanize, shortId } from "@/lib/format";
import { useIdempotencyKey } from "@/lib/idempotency";
import { jobStatus } from "@/lib/job-status";
import { safeGitHubRepoUrl } from "@/lib/security";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";
import { useWorkspace } from "./context";
import { repositoryLabel, StatusBadge } from "./records";
import { useAction } from "./use-action";

const REFRESH_MS = 5000;

function measurement(value: unknown): string {
  return typeof value === "number" ? value.toFixed(3) : String(value);
}

export function JobDetailView({ jobId }: { jobId: string }) {
  const { handleUnauthorized, refresh, sessionSignal, signingOut } = useWorkspace();
  const [job, setJob] = useState<Job | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [loading, setLoading] = useState(true);
  const action = useAction("cancel");
  const retryKey = useIdempotencyKey();

  // Cancelled by unmounting or by signing out, which then shows nothing.
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const link = linkAbort(sessionSignal, signal);
      if (link.signal.aborted) return;
      try {
        const found = await api<Job>(`/jobs/${jobId}`, { signal: link.signal });
        if (link.signal.aborted) return;
        setJob(found);
        setProblem(null);
      } catch (cause) {
        if (link.signal.aborted) return;
        if (!handleUnauthorized(cause)) setProblem(toProblem(cause));
      } finally {
        link.release();
        if (!link.signal.aborted) setLoading(false);
      }
    },
    [jobId, handleUnauthorized, sessionSignal],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  const active = job !== null && ACTIVE_JOB_STATES.includes(job.state);
  useVisibilityPolling(() => load(), REFRESH_MS, active && !signingOut);

  if (!job)
    return loading ? (
      <section className="panel" aria-busy="true">
        <SkeletonRows rows={4} />
      </section>
    ) : (
      <>
        <PageHeader title="Job unavailable" />
        {problem && <ProblemNotice problem={problem} onRetry={() => void load()} />}
        <Link href="/jobs">Back to job history</Link>
      </>
    );

  const outcome = describeJobOutcome(job.error_code);
  const status = jobStatus(job);
  const boundary = status.boundary;
  const repository = job.repository_url ? safeGitHubRepoUrl(job.repository_url) : null;
  const stages = job.stages ?? [];

  async function cancel() {
    const ok = await action.run(() => api(`/jobs/${job!.id}/cancel`, { method: "POST" }));
    if (ok) await Promise.all([load(), refresh()]);
  }
  async function retry() {
    let failure: unknown;
    const ok = await action.run(() =>
      api(`/development/jobs/${job!.id}/retry`, {
        method: "POST",
        idempotencyKey: retryKey.current(),
      }).catch((cause: unknown) => {
        failure = cause;
        throw cause;
      }),
    );
    if (ok || (failure instanceof ApiError && failure.code === "idempotency_conflict"))
      retryKey.rotate();
    if (ok) await Promise.all([load(), refresh()]);
  }

  return (
    <>
      <PageHeader
        eyebrow={`Job ${shortId(job.id)}`}
        title={job.synthetic ? "Synthetic fixture" : "Repository analysis"}
        description={
          job.synthetic
            ? "Trusted development fixture · No repository acquisition, AI, audio or video processing."
            : "Static analysis of one pinned commit · Repository code is never run."
        }
        actions={<StatusBadge status={status} />}
      />
      {problem && <ProblemNotice problem={problem} onRetry={() => void load()} />}
      {outcome && (
        <div className="notice" data-tone={boundary ? "success" : "warning"}>
          <div>
            <p>{outcome}</p>
            {!boundary && <small className="problem-meta">Reference: {job.error_code}</small>}
          </div>
        </div>
      )}
      {job.state === "failed" && !boundary && <RemediationPanel code={job.error_code} />}
      <section className="panel" aria-labelledby="job-summary">
        <div className="panel-header">
          <h2 id="job-summary">Summary</h2>
          <div className="actions">
            {active && (
              <button type="button" disabled={action.busy} onClick={() => void cancel()}>
                {job.synthetic ? "Cancel fixture" : "Cancel analysis"}
              </button>
            )}
            {["failed", "cancelled"].includes(job.state) && !boundary && (
              <button type="button" disabled={action.busy} onClick={() => void retry()}>
                {job.synthetic ? "Retry as a new fixture" : "Retry pinned analysis"}
              </button>
            )}
          </div>
        </div>
        <div className="panel-body">
          {action.problem && <ProblemNotice problem={action.problem} />}
          <dl className="definition-list">
            {job.project_title && (
              <>
                <dt>Project</dt>
                <dd>
                  <Link href={`/projects/${encodeURIComponent(job.project_id)}`}>
                    {job.project_title}
                  </Link>
                </dd>
              </>
            )}
            {!job.synthetic && (
              <>
                <dt>Repository</dt>
                <dd>
                  {repository ? (
                    <ExternalLink href={repository}>{repositoryLabel(repository)}</ExternalLink>
                  ) : (
                    <span className="mono">{job.repository_url ?? "Not recorded"}</span>
                  )}
                </dd>
                <dt>Pinned commit</dt>
                <dd>
                  {job.commit_sha ? <code className="sha">{job.commit_sha}</code> : "Not yet resolved"}
                </dd>
              </>
            )}
            <dt>Created</dt>
            <dd>{formatDateTime(job.created_at)}</dd>
            <dt>Deadline</dt>
            <dd>{formatDateTime(job.deadline)}</dd>
            {job.finished_at && (
              <>
                <dt>Finished</dt>
                <dd>{formatDateTime(job.finished_at)}</dd>
              </>
            )}
            {job.pipeline_version && (
              <>
                <dt>Pipeline</dt>
                <dd>
                  <code>{job.pipeline_version}</code>
                </dd>
              </>
            )}
          </dl>
          <details className="disclosure technical-details" open={boundary}>
            <summary>Technical details</summary>
            <dl className="definition-list">
              <dt>Recorded state</dt>
              <dd>
                <code>{job.state}</code>
              </dd>
              <dt>Stop code</dt>
              <dd>{job.error_code ? <code>{job.error_code}</code> : "None"}</dd>
              <dt>Record version</dt>
              <dd>
                <code>{job.version}</code>
              </dd>
            </dl>
            {boundary && (
              <p className="field-hint">
                The API records the normal end of this pipeline as <code>failed</code> with a
                boundary code. It is shown as {status.label} because nothing went wrong.
              </p>
            )}
          </details>
        </div>
      </section>
      {!job.synthetic && job.error_code === "phase2_pipeline_boundary" && (
        <AnalysisPanel jobId={job.id} />
      )}
      <section className="panel" aria-labelledby="job-stages">
        <div className="panel-header">
          <h2 id="job-stages">Pipeline stages</h2>
          <span className="panel-meta">{stages.length} stages</span>
        </div>
        <ol className="stage-list">
          {stages.map((stage) => (
            <li key={stage.id}>
              <span className="stage-number">{stage.ordinal.toString().padStart(2, "0")}</span>
              <span className="stage-key">{stage.stage_key}</span>
              <span className="stage-attempts">
                {stage.attempt_count} {stage.attempt_count === 1 ? "attempt" : "attempts"}
              </span>
              <Badge state={stage.state} />
            </li>
          ))}
        </ol>
      </section>
      <section className="panel" aria-labelledby="job-history">
        <div className="panel-header">
          <h2 id="job-history">History</h2>
        </div>
        <div className="panel-body">
          <h3 className="section-title">State history</h3>
          <ul className="history-list">
            {job.history?.map((entry) => (
              <li key={entry.version}>
                <span className="mono">v{entry.version}</span>
                <StatusBadge
                  status={jobStatus({ ...entry, error_code: entry.error_code ?? null, synthetic: job.synthetic })}
                />
                <time dateTime={entry.created_at}>{formatDate(entry.created_at)}</time>
              </li>
            ))}
          </ul>
          <h3 className="section-title">Attempt history</h3>
          {job.attempts?.length ? (
            <ul className="plain-list">
              {job.attempts.map((attempt) => (
                <li key={`${attempt.stage_id}-${attempt.attempt_no}`}>
                  Attempt {attempt.attempt_no} · {humanize(attempt.outcome)}
                  {attempt.error_code && (
                    <>
                      {" "}
                      · <code>{attempt.error_code}</code>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p>No attempts recorded yet.</p>
          )}
          <h3 className="section-title">Usage ledger</h3>
          {job.usage?.length ? (
            <ul className="plain-list">
              {job.usage.map((entry, index) => (
                <li key={index}>
                  {entry.event_type} · {entry.units}{" "}
                  {job.synthetic ? "fixture unit" : "reservation unit"}
                  {!job.synthetic &&
                    Object.entries(entry.measurements).map(([name, value]) => (
                      <span key={name}>
                        {" "}
                        · {name}: {measurement(value)}
                      </span>
                    ))}
                </li>
              ))}
            </ul>
          ) : (
            <p>No usage recorded yet.</p>
          )}
        </div>
      </section>
    </>
  );
}
