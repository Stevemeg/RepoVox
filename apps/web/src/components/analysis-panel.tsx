"use client";
import { useEffect, useState } from "react";
import { ExternalLink } from "@/components/ui/external-link";
import { api, ApiError } from "@/lib/api";
import { toProblem } from "@/lib/errors";
import { safePermalink } from "@/lib/security";

// Re-exported for existing importers; the validator now lives in lib/security.ts.
export { safePermalink };

type Evidence = {
  id: string;
  path: string;
  start_line: number;
  end_line: number;
  permalink: string;
  excerpt: string;
  validation_status: string;
  redacted: boolean;
};
type Analysis = {
  commit_sha: string;
  payload: {
    knowledge: {
      repository: { canonical_url: string };
      stack: string[];
      modules: string[];
      nodes?: { id: string; path: string; name: string }[];
      entrypoints: {
        candidates: {
          symbol_id: string;
          path: string;
          rule: string;
          qualification?: string;
        }[];
        uncertainty: string[];
      };
      edges: {
        id: string;
        source: string;
        target: string;
        relationship: string;
        classification: string;
        qualification: string;
      }[];
      claims: { id: string; text: string; status: string; reason: string }[];
      coverage: {
        coverage: number;
        parsed_bytes: number;
        eligible_bytes: number;
        files: { path: string; status: string; reason: string }[];
      };
      limitations: string[];
    };
    evidence: { items: Evidence[] };
    verification: { counts: Record<string, number>; conflicts: string[] };
  };
};

export function AnalysisPanel({ jobId }: { jobId: string }) {
  const [current, setCurrent] = useState<{
    jobId: string;
    result?: Analysis;
    message?: string;
  } | null>(null);
  const result = current?.jobId === jobId ? current.result : undefined;
  const message =
    current?.jobId === jobId ? current.message : "Loading verified analysis…";
  useEffect(() => {
    const controller = new AbortController();
    api<Analysis>(`/development/jobs/${jobId}/analysis`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) setCurrent({ jobId, result: value });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setCurrent({
            jobId,
            message:
              error instanceof ApiError && error.status === 404
                ? "Verified analysis is not available yet or has expired."
                : toProblem(error).message,
          });
      });
    return () => controller.abort();
  }, [jobId]);
  if (!result)
    return (
      <section className="panel" aria-busy={!current}>
        <div className="panel-body">
          <p role="status">{message}</p>
        </div>
      </section>
    );
  const { knowledge, evidence, verification } = result.payload;
  const names = new Map(
    knowledge.nodes?.map((node) => [node.id, `${node.path}: ${node.name}`]),
  );
  return (
    <section className="panel" aria-labelledby="verified-analysis">
      <div className="panel-header">
        <h2 id="verified-analysis">Verified static analysis</h2>
        <span className="panel-meta">Stages 1–9 · read as data, never run</span>
      </div>
      <div className="panel-body">
        <dl className="definition-list">
          <dt>Repository</dt>
          <dd>{knowledge.repository.canonical_url}</dd>
          <dt>Pinned commit</dt>
          <dd>
            <code className="sha">{result.commit_sha}</code>
          </dd>
          <dt>Languages</dt>
          <dd>{knowledge.stack.join(", ")}</dd>
          <dt>Examined files</dt>
          <dd>
            {knowledge.coverage.files.length} total ·{" "}
            {
              knowledge.coverage.files.filter((file) => file.status === "parsed")
                .length
            }{" "}
            parsed
          </dd>
          <dt>Parsed eligible bytes</dt>
          <dd>
            {knowledge.coverage.parsed_bytes} /{" "}
            {knowledge.coverage.eligible_bytes} (
            {(knowledge.coverage.coverage * 100).toFixed(1)}%)
          </dd>
        </dl>
        <h3 className="section-title">Claim verdicts</h3>
        <ul className="bullet-list">
          {Object.entries(verification.counts).map(([status, count]) => (
            <li key={status}>
              {status.replaceAll("_", " ")}: {count}
            </li>
          ))}
        </ul>
        <h3 className="section-title">Modules ({knowledge.modules.length})</h3>
        <ul className="bullet-list">
          {knowledge.modules.slice(0, 50).map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <h3 className="section-title">Entrypoint candidates</h3>
        <ul className="bullet-list">
          {knowledge.entrypoints.candidates.map((entry, i) => (
            <li key={`${entry.symbol_id}-${i}`}>
              {entry.path} · {entry.rule} ·{" "}
              {entry.qualification || "Static candidate; execution unknown"}
            </li>
          ))}
        </ul>
        <h3 className="section-title">Qualified relationships ({knowledge.edges.length})</h3>
        <ul className="bullet-list">
          {knowledge.edges.slice(0, 50).map((edge) => (
            <li key={edge.id}>
              {edge.relationship} · {edge.classification} ·{" "}
              <code>
                {names.get(edge.source) || edge.source} →{" "}
                {names.get(edge.target) || edge.target}
              </code>
              <br />
              {edge.qualification}
            </li>
          ))}
        </ul>
        <h3 className="section-title">Technical claims</h3>
        <ul className="bullet-list">
          {knowledge.claims.slice(0, 50).map((claim) => (
            <li key={claim.id}>
              <strong>{claim.status.replaceAll("_", " ")}</strong>: {claim.text}
              <br />
              {claim.reason}
            </li>
          ))}
        </ul>
        <h3 className="section-title">Source evidence</h3>
        {evidence.items
          .filter((e) => e.validation_status === "valid")
          .slice(0, 30)
          .map((item) => {
            const permalink = safePermalink(item.permalink, result.commit_sha);
            return (
              <details className="evidence" key={item.id}>
                <summary>
                  {item.path}:{item.start_line}–{item.end_line}
                  {item.redacted && " · redacted"}
                </summary>
                {permalink && (
                  <ExternalLink href={permalink}>Pinned source permalink</ExternalLink>
                )}
                <pre className="code-block">{item.excerpt}</pre>
              </details>
            );
          })}
        <h3 className="section-title">Omissions and uncertainty</h3>
        <ul className="bullet-list">
          {[
            ...knowledge.limitations,
            ...knowledge.entrypoints.uncertainty,
            ...verification.conflicts,
          ].map((text, i) => (
            <li key={i}>{text}</li>
          ))}
        </ul>
        <details className="disclosure">
          <summary>Skipped or failed files</summary>
          <ul className="bullet-list">
            {knowledge.coverage.files
              .filter((f) => ["skipped", "failed"].includes(f.status))
              .map((file) => (
                <li key={file.path}>
                  {file.path} · {file.reason}
                </li>
              ))}
          </ul>
        </details>
        <p className="field-hint">
          Lists show the first 50 records and 30 citations. The authorized JSON
          endpoint contains the full analysis.
        </p>
      </div>
    </section>
  );
}
