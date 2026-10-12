"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

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

export function safePermalink(value: string, sha: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "github.com" &&
      !url.port &&
      !url.username &&
      !url.password &&
      !url.search &&
      /^[a-f0-9]{40}$/.test(sha) &&
      url.pathname.includes(`/blob/${sha}/`) &&
      /^#L[1-9][0-9]*-L[1-9][0-9]*$/.test(url.hash)
    );
  } catch {
    return false;
  }
}

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
                : "Analysis is unavailable in this session.",
          });
      });
    return () => controller.abort();
  }, [jobId]);
  if (!result)
    return (
      <section className="panel details">
        <p role="status">{message}</p>
      </section>
    );
  const { knowledge, evidence, verification } = result.payload;
  const names = new Map(
    knowledge.nodes?.map((node) => [node.id, `${node.path}: ${node.name}`]),
  );
  return (
    <section className="panel details">
      <h2>Verified static analysis</h2>
      <p>Development analysis · Stages 1–9 · No video generated</p>
      <dl>
        <dt>Repository</dt>
        <dd>{knowledge.repository.canonical_url}</dd>
        <dt>Pinned commit</dt>
        <dd>
          <code>{result.commit_sha}</code>
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
      <h3>Claim verdicts</h3>
      <ul>
        {Object.entries(verification.counts).map(([status, count]) => (
          <li key={status}>
            {status.replaceAll("_", " ")}: {count}
          </li>
        ))}
      </ul>
      <h3>Modules ({knowledge.modules.length})</h3>
      <ul>
        {knowledge.modules.slice(0, 50).map((name) => (
          <li key={name}>{name}</li>
        ))}
      </ul>
      <h3>Entrypoint candidates</h3>
      <ul>
        {knowledge.entrypoints.candidates.map((entry, i) => (
          <li key={`${entry.symbol_id}-${i}`}>
            {entry.path} · {entry.rule} ·{" "}
            {entry.qualification || "Static candidate; execution unknown"}
          </li>
        ))}
      </ul>
      <h3>Qualified relationships ({knowledge.edges.length})</h3>
      <ul>
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
      <h3>Technical claims</h3>
      <ul>
        {knowledge.claims.slice(0, 50).map((claim) => (
          <li key={claim.id}>
            <strong>{claim.status.replaceAll("_", " ")}</strong>: {claim.text}
            <br />
            {claim.reason}
          </li>
        ))}
      </ul>
      <h3>Source evidence</h3>
      {evidence.items
        .filter((e) => e.validation_status === "valid")
        .slice(0, 30)
        .map((item) => (
          <details key={item.id}>
            <summary>
              {item.path}:{item.start_line}–{item.end_line}
              {item.redacted && " · redacted"}
            </summary>
            {safePermalink(item.permalink, result.commit_sha) && (
              <a href={item.permalink} target="_blank" rel="noreferrer">
                Pinned source permalink
              </a>
            )}
            <pre>{item.excerpt}</pre>
          </details>
        ))}
      <h3>Omissions and uncertainty</h3>
      <ul>
        {[
          ...knowledge.limitations,
          ...knowledge.entrypoints.uncertainty,
          ...verification.conflicts,
        ].map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
      <details>
        <summary>Skipped or failed files</summary>
        <ul>
          {knowledge.coverage.files
            .filter((f) => ["skipped", "failed"].includes(f.status))
            .map((file) => (
              <li key={file.path}>
                {file.path} · {file.reason}
              </li>
            ))}
        </ul>
      </details>
      <p>
        Lists show the first 50 records and 30 citations. The authorized JSON
        endpoint contains the full analysis.
      </p>
    </section>
  );
}
