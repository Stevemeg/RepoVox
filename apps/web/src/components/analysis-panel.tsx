"use client";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Badge, type Tone } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/external-link";
import { api, ApiError } from "@/lib/api";
import { toProblem } from "@/lib/errors";
import { humanize } from "@/lib/format";
import { safeGitHubRepoUrl, safePermalink } from "@/lib/security";

// Re-exported for existing importers; the validator now lives in lib/security.ts.
export { safePermalink };

/*
 * The verified Stage 1-9 analysis, rendered strictly as text. Repository-derived strings
 * (paths, names, excerpts, claims) are untrusted: they only ever become React text nodes,
 * and a citation becomes a link only through `safePermalink(..., commit_sha)`, which pins
 * it to this analysis's exact commit, then `<ExternalLink>`.
 */

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
type FileRecord = {
  path: string;
  status: string;
  reason: string;
  language?: string;
  classification?: string;
  bytes?: number;
};
type Analysis = {
  commit_sha: string;
  payload: {
    knowledge: {
      repository: { canonical_url: string };
      stack: string[];
      frameworks?: { name: string; qualification?: string }[];
      modules: string[];
      nodes?: { id: string; path: string; name: string }[];
      entrypoints: {
        candidates: {
          symbol_id: string;
          path: string;
          rule: string;
          category?: string;
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
        files: FileRecord[];
      };
      limitations: string[];
      versions?: { pipeline?: string; schema?: string };
    };
    evidence: { items: Evidence[] };
    verification: { counts: Record<string, number>; conflicts: string[] };
  };
};

/** Records each list shows at first, and how many more "Show more" reveals. */
export const DISPLAY_CAP = 50;
const BUDGET_PREFIX = "Test-fact budget:";
const WEIGHT_REASON = "ml_weight_container";
const BUDGET_REASONS = new Set([
  "parsed_test_calls_omitted",
  "parsed_test_calls_imports_omitted",
  "parsed_test_facts_omitted",
]);
const VERDICT_TONES: Record<string, Tone> = {
  verified: "verified",
  inferred: "inferred",
  documentation_only: "author-stated",
  unsupported: "unverified",
};

const SECTIONS = [
  { id: "overview", label: "Overview & coverage" },
  { id: "structure", label: "Modules & entrypoints" },
  { id: "claims", label: "Claims" },
  { id: "evidence", label: "Code evidence" },
  { id: "limitations", label: "Limitations & skipped files" },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];

const list = <T,>(value: T[] | undefined | null): T[] => (Array.isArray(value) ? value : []);

/** Plain, case-insensitive substring matching; the query is never a pattern. */
const matcher = (query: string) => {
  const needle = query.trim().toLowerCase();
  return (...fields: (string | number | undefined | null)[]) =>
    !needle || fields.some((field) => String(field ?? "").toLowerCase().includes(needle));
};

/**
 * A list that shows `DISPLAY_CAP` records at a time and always says how many it shows, so
 * nothing is ever truncated silently.
 */
function CappedList<T>({
  items,
  total,
  noun,
  filtered,
  render,
  empty,
  className = "bullet-list",
}: {
  items: T[];
  total: number;
  noun: string;
  filtered: boolean;
  render: (item: T, index: number) => ReactNode;
  empty: string;
  className?: string;
}) {
  const [limit, setLimit] = useState(DISPLAY_CAP);
  const visible = items.slice(0, limit);
  if (items.length === 0)
    return <p className="field-hint">{filtered && total > 0 ? `No ${noun} match this search.` : empty}</p>;
  const scope = filtered ? ` matching (${total} in total)` : "";
  return (
    <>
      <p className="cap-note">
        {visible.length < items.length
          ? `Showing ${visible.length} of ${items.length} ${noun}${scope}.`
          : `Showing all ${items.length} ${noun}${scope}.`}
      </p>
      <ul className={className}>{visible.map(render)}</ul>
      {visible.length < items.length && (
        <button
          type="button"
          className="button-ghost"
          onClick={() => setLimit((current) => current + DISPLAY_CAP)}
        >
          Show {Math.min(DISPLAY_CAP, items.length - visible.length)} more {noun}
        </button>
      )}
    </>
  );
}

function AnalysisExplorer({ result }: { result: Analysis }) {
  const { knowledge, evidence, verification } = result.payload;
  const [section, setSection] = useState<SectionId>("overview");
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("all");
  const base = useId();
  const tabs = useRef<Partial<Record<SectionId, HTMLButtonElement | null>>>({});
  const match = matcher(query);
  const searching = query.trim() !== "";

  const modules = list(knowledge.modules);
  const candidates = list(knowledge.entrypoints?.candidates);
  const edges = list(knowledge.edges);
  const claims = list(knowledge.claims);
  const items = list(evidence?.items);
  const files = list(knowledge.coverage?.files);
  const names = new Map(list(knowledge.nodes).map((node) => [node.id, `${node.path}: ${node.name}`]));
  const label = (id: string) => names.get(id) || id;

  const shownModules = modules.filter((name) => match(name));
  const shownCandidates = candidates.filter((entry) =>
    match(entry.path, entry.rule, entry.category, entry.qualification),
  );
  const shownEdges = edges.filter((edge) =>
    match(edge.relationship, edge.classification, label(edge.source), label(edge.target), edge.qualification),
  );
  const verdicts = [...new Set(claims.map((claim) => claim.status))].sort();
  const activeVerdict = verdict === "all" || verdicts.includes(verdict) ? verdict : "all";
  const verdictClaims = claims.filter((claim) => activeVerdict === "all" || claim.status === activeVerdict);
  const shownClaims = verdictClaims.filter((claim) => match(claim.text, claim.reason, claim.status));
  const valid = items.filter((item) => item.validation_status === "valid");
  const shownEvidence = valid.filter((item) => match(item.path, item.excerpt));
  const skipped = files.filter((file) => file.status === "skipped" || file.status === "failed");
  const shownSkipped = skipped.filter((file) => match(file.path, file.reason));
  const weights = files.filter((file) => file.reason === WEIGHT_REASON);
  const budgeted = files.filter((file) => BUDGET_REASONS.has(file.reason));
  const limitations = list(knowledge.limitations);
  const budgetLines = limitations.filter((line) => line.startsWith(BUDGET_PREFIX));
  const otherLimitations = limitations.filter((line) => !line.startsWith(BUDGET_PREFIX));
  const uncertainty = list(knowledge.entrypoints?.uncertainty);
  const conflicts = list(verification?.conflicts);
  const statusCounts = files.reduce<Record<string, number>>((counts, file) => {
    counts[file.status] = (counts[file.status] ?? 0) + 1;
    return counts;
  }, {});
  const coverage = knowledge.coverage ?? { coverage: 0, parsed_bytes: 0, eligible_bytes: 0 };
  const repository = safeGitHubRepoUrl(knowledge.repository?.canonical_url);

  const counts: Record<SectionId, number | null> = {
    overview: null,
    structure: shownModules.length + shownCandidates.length + shownEdges.length,
    claims: shownClaims.length,
    evidence: shownEvidence.length,
    limitations: shownSkipped.length,
  };

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const index = SECTIONS.findIndex((item) => item.id === section);
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % SECTIONS.length
        : event.key === "ArrowLeft"
          ? (index - 1 + SECTIONS.length) % SECTIONS.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? SECTIONS.length - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    const id = SECTIONS[next].id;
    setSection(id);
    tabs.current[id]?.focus();
  }

  return (
    <section className="panel" aria-labelledby={`${base}-title`}>
      <div className="panel-header">
        <h2 id={`${base}-title`}>Verified static analysis</h2>
        <span className="panel-meta">Stages 1–9 · read as data, never run</span>
      </div>
      <div className="panel-body analysis-explorer">
        <div className="analysis-toolbar" role="search" aria-label="Analysis search">
          <div className="field">
            <label htmlFor={`${base}-search`}>Search this analysis</label>
            <input
              id={`${base}-search`}
              type="search"
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Module, path, claim or code excerpt"
              maxLength={200}
              autoComplete="off"
              spellCheck={false}
              aria-describedby={`${base}-search-hint`}
            />
            <small id={`${base}-search-hint`} className="field-hint">
              Filters modules, entrypoints, relationships, claims, code evidence and skipped
              files. Limitations are always shown in full.
            </small>
          </div>
        </div>
        <div className="tabs" role="tablist" aria-label="Analysis sections">
          {SECTIONS.map((item) => {
            const selected = item.id === section;
            const count = counts[item.id];
            return (
              <button
                key={item.id}
                ref={(element) => {
                  tabs.current[item.id] = element;
                }}
                type="button"
                role="tab"
                id={`${base}-tab-${item.id}`}
                aria-selected={selected}
                aria-controls={`${base}-panel-${item.id}`}
                tabIndex={selected ? 0 : -1}
                className="tab"
                onClick={() => setSection(item.id)}
                onKeyDown={onTabKey}
              >
                {item.label}
                {count !== null && (
                  <span className="tab-count">
                    <span className="visually-hidden">, </span>
                    {count}
                    <span className="visually-hidden">{searching ? " matching" : " records"}</span>
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {SECTIONS.filter((item) => item.id !== section).map((item) => (
          // Every tab controls a real panel; only the selected one has content.
          <div
            key={item.id}
            className="tab-panel"
            role="tabpanel"
            id={`${base}-panel-${item.id}`}
            aria-labelledby={`${base}-tab-${item.id}`}
            hidden
          />
        ))}
        <div
          // Keyed by section: a switch remounts the panel, which replays its CSS reveal.
          key={section}
          className="tab-panel"
          role="tabpanel"
          id={`${base}-panel-${section}`}
          aria-labelledby={`${base}-tab-${section}`}
          tabIndex={0}
        >
          {section === "overview" && (
            <>
              <dl className="definition-list">
                <dt>Repository</dt>
                <dd>
                  {repository ? (
                    <ExternalLink href={repository}>{knowledge.repository.canonical_url}</ExternalLink>
                  ) : (
                    <span className="mono">{knowledge.repository?.canonical_url ?? "Not recorded"}</span>
                  )}
                </dd>
                <dt>Pinned commit</dt>
                <dd>
                  <code className="sha">{result.commit_sha}</code>
                </dd>
                <dt>Languages</dt>
                <dd>{list(knowledge.stack).join(", ") || "None detected"}</dd>
                {list(knowledge.frameworks).length > 0 && (
                  <>
                    <dt>Frameworks</dt>
                    <dd>{list(knowledge.frameworks).map((framework) => framework.name).join(", ")}</dd>
                  </>
                )}
                <dt>Examined files</dt>
                <dd>
                  {files.length} total
                  {Object.entries(statusCounts)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([status, count]) => (
                      <span key={status}>
                        {" "}
                        · {count} {humanize(status)}
                      </span>
                    ))}
                </dd>
                <dt>Parsed eligible bytes</dt>
                <dd>
                  {coverage.parsed_bytes} / {coverage.eligible_bytes} (
                  {(coverage.coverage * 100).toFixed(1)}%)
                </dd>
                {knowledge.versions?.pipeline && (
                  <>
                    <dt>Pipeline</dt>
                    <dd>
                      <code>{knowledge.versions.pipeline}</code>
                    </dd>
                  </>
                )}
              </dl>
              <h3 className="section-title">Claim verdicts</h3>
              <ul className="bullet-list">
                {Object.entries(verification?.counts ?? {}).map(([status, count]) => (
                  <li key={status}>
                    {humanize(status)}: {count}
                  </li>
                ))}
              </ul>
              {(budgetLines.length > 0 || weights.length > 0) && (
                <p className="field-hint">
                  This analysis has disclosures about omitted test facts or skipped model
                  weights. See Limitations &amp; skipped files.
                </p>
              )}
            </>
          )}

          {section === "structure" && (
            <>
              <h3 className="section-title">Modules</h3>
              <CappedList
                items={shownModules}
                total={modules.length}
                noun="modules"
                filtered={searching}
                empty="No modules were recorded."
                render={(name) => (
                  <li key={name}>
                    <code>{name}</code>
                  </li>
                )}
              />
              <h3 className="section-title">Entrypoint candidates</h3>
              <CappedList
                items={shownCandidates}
                total={candidates.length}
                noun="entrypoint candidates"
                filtered={searching}
                empty="No entrypoint candidate was found."
                render={(entry, index) => (
                  <li key={`${entry.symbol_id}-${index}`}>
                    <code>{entry.path}</code> · {entry.rule}
                    {entry.category && <> · {humanize(entry.category)}</>} ·{" "}
                    {entry.qualification || "Static candidate; execution unknown"}
                  </li>
                )}
              />
              <h3 className="section-title">Qualified relationships</h3>
              <CappedList
                items={shownEdges}
                total={edges.length}
                noun="relationships"
                filtered={searching}
                empty="No qualified relationship was recorded."
                render={(edge) => (
                  <li key={edge.id}>
                    {edge.relationship} · {edge.classification} ·{" "}
                    <code>
                      {label(edge.source)} → {label(edge.target)}
                    </code>
                    <br />
                    {edge.qualification}
                  </li>
                )}
              />
            </>
          )}

          {section === "claims" && (
            <>
              <div className="field claim-filter">
                <label htmlFor={`${base}-verdict`}>Claim verdict</label>
                <select
                  id={`${base}-verdict`}
                  className="input"
                  value={activeVerdict}
                  onChange={(event) => setVerdict(event.target.value)}
                >
                  <option value="all">All verdicts ({claims.length})</option>
                  {verdicts.map((status) => (
                    <option key={status} value={status}>
                      {humanize(status)} ({claims.filter((claim) => claim.status === status).length})
                    </option>
                  ))}
                </select>
              </div>
              <CappedList
                items={shownClaims}
                total={verdictClaims.length}
                noun="claims"
                filtered={searching}
                empty={
                  activeVerdict === "all"
                    ? "No technical claims were recorded."
                    : "No claims have this verdict."
                }
                className="claim-list"
                render={(claim) => (
                  <li key={claim.id} className="claim">
                    <Badge
                      state={claim.status}
                      label={humanize(claim.status)}
                      tone={VERDICT_TONES[claim.status] ?? "neutral"}
                    />
                    <p>{claim.text}</p>
                    <small className="field-hint">{claim.reason}</small>
                  </li>
                )}
              />
            </>
          )}

          {section === "evidence" && (
            <>
              {items.length > valid.length && (
                <p className="field-hint">
                  {items.length - valid.length} evidence{" "}
                  {items.length - valid.length === 1 ? "record" : "records"} did not pass
                  validation and {items.length - valid.length === 1 ? "is" : "are"} not shown.
                </p>
              )}
              <CappedList
                items={shownEvidence}
                total={valid.length}
                noun="citations"
                filtered={searching}
                empty="No validated source evidence was recorded."
                className="evidence-list"
                render={(item) => {
                  const permalink = safePermalink(item.permalink, result.commit_sha);
                  return (
                    <li key={item.id}>
                      <details className="evidence">
                        <summary>
                          {item.path}:{item.start_line}–{item.end_line}
                          {item.redacted && " · redacted"}
                        </summary>
                        {permalink ? (
                          <ExternalLink href={permalink}>Pinned source permalink</ExternalLink>
                        ) : (
                          <p className="field-hint">
                            No link: this citation&apos;s permalink did not match the pinned
                            commit.
                          </p>
                        )}
                        <pre className="code-block">{item.excerpt}</pre>
                      </details>
                    </li>
                  );
                }}
              />
            </>
          )}

          {section === "limitations" && (
            <>
              {budgetLines.map((line) => (
                <div key={line} className="notice" data-tone="warning" data-disclosure="test-fact-budget">
                  <p>{line}</p>
                </div>
              ))}
              <h3 className="section-title">Limitations</h3>
              <ul className="bullet-list">
                {otherLimitations.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
              {(uncertainty.length > 0 || conflicts.length > 0) && (
                <>
                  <h3 className="section-title">Uncertainty and conflicts</h3>
                  <ul className="bullet-list">
                    {[...uncertainty, ...conflicts].map((text, index) => (
                      <li key={index}>{text}</li>
                    ))}
                  </ul>
                </>
              )}
              {weights.length > 0 && (
                <>
                  <h3 className="section-title">Model weight files ({weights.length})</h3>
                  <p className="field-hint">
                    PyTorch and Keras weight containers are hashed and screened for
                    credentials, then skipped: never written, unpacked or parsed.
                  </p>
                  <ul className="bullet-list">
                    {weights.map((file) => (
                      <li key={file.path}>
                        <code>{file.path}</code>
                        {typeof file.bytes === "number" && <> · {file.bytes} bytes</>}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {budgeted.length > 0 && (
                <>
                  <h3 className="section-title">Test files with omitted facts ({budgeted.length})</h3>
                  <ul className="bullet-list">
                    {budgeted.map((file) => (
                      <li key={file.path}>
                        <code>{file.path}</code> · {humanize(file.reason)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <h3 className="section-title">Skipped and failed files</h3>
              <CappedList
                items={shownSkipped}
                total={skipped.length}
                noun="skipped or failed files"
                filtered={searching}
                empty="No file was skipped or failed."
                render={(file) => (
                  <li key={file.path}>
                    <code>{file.path}</code> · {humanize(file.status)} · {humanize(file.reason)}
                  </li>
                )}
              />
            </>
          )}
        </div>
        <p className="field-hint">
          The authorized analysis endpoint contains the full record; this view never hides a
          list without saying how much of it is shown.
        </p>
      </div>
    </section>
  );
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
  return <AnalysisExplorer key={jobId} result={result} />;
}
