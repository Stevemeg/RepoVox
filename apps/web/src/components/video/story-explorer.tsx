"use client";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { BookOpen, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { humanize } from "@/lib/format";
import { describeProvenance } from "@/lib/narration";
import {
  CLAIM_STATUSES,
  CLAIM_TONES,
  claimIndex,
  type StoryClaim,
  type StoryView,
  type VideoStoryView,
} from "@/lib/story-types";
import type { Video } from "@/lib/types";
import {
  ClaimList,
  domId,
  StoryContext,
  type ClaimMismatch,
  type StoryContextValue,
} from "./story-claims";
import { MismatchInspector } from "./story-mismatches";
import type { StoryState } from "./use-video-story";

/*
 * The Problem-to-Solution story of a walkthrough (ADR-0025), held to the frontend handoff's
 * truthfulness rules: literal status badges on every claim, mismatches listed in full, an
 * explicit notice when the repository does not document its problem, the outcome scope
 * shown verbatim ("read, not run"), the narration's provenance, and repository strings as
 * text only with commit-pinned links.
 */

const TABS = [
  { id: "summary", label: "Summary & mismatches" },
  { id: "problem", label: "Problem & solution" },
  { id: "implementation", label: "Implementation & architecture" },
  { id: "outcomes", label: "Outcomes, limitations & open questions" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** Story sections shown in full, in tab order. Claims are anchored in the first one. */
type Section = { tab: TabId; key: string; claims: (story: StoryView) => StoryClaim[] };
const SECTIONS: Section[] = [
  { tab: "problem", key: "problem_statement", claims: (s) => s.problem_statement.claims },
  { tab: "problem", key: "problem_context", claims: (s) => s.problem_context.claims },
  { tab: "problem", key: "intended_solution", claims: (s) => s.intended_solution.claims },
  { tab: "implementation", key: "implementation_approach", claims: (s) => s.implementation_approach.claims },
  { tab: "implementation", key: "decisions", claims: (s) => s.implementation_approach.decisions },
  { tab: "implementation", key: "architecture", claims: (s) => s.architecture.claims },
  { tab: "implementation", key: "workflow", claims: (s) => s.architecture.workflow },
  { tab: "implementation", key: "implementation_evidence", claims: (s) => s.implementation_evidence.claims },
  { tab: "outcomes", key: "demonstrated_outcomes", claims: (s) => s.demonstrated_outcomes.claims },
  { tab: "outcomes", key: "limitations", claims: (s) => s.limitations.claims },
  { tab: "outcomes", key: "unresolved_questions", claims: (s) => s.unresolved_questions.claims },
];

const SOURCE_LABELS: Record<string, string> = {
  readme: "README",
  documentation: "Documentation",
  manifest: "Manifests",
  source: "Source",
  test: "Tests",
  example: "Examples",
};

const plural = (value: number, one: string, many = `${one}s`) =>
  `${value} ${value === 1 ? one : many}`;

function SectionTitle({ children }: { children: string }) {
  return <h5 className="story-section-title">{children}</h5>;
}

/** The narration record from the story API, as one line. */
function narrationSummary(view: VideoStoryView): string {
  const provenance = describeProvenance("walkthrough", view.narration);
  if (!provenance.recorded) return "Not recorded for this story.";
  const wording = provenance.wording;
  const words =
    wording?.kind === "template"
      ? "Deterministic template wording (no language model)"
      : wording?.kind === "model"
        ? `Reworded by a language model: ${wording.model ?? "model not named"} via ${wording.provider}, ${wording.scenesRefined} of ${wording.scenesTotal} scenes`
        : "Wording not recorded";
  const voice = provenance.voice;
  const spoken = voice?.recorded
    ? `voice ${[voice.provider, voice.engine, voice.voice].filter(Boolean).join(" / ")}`
    : "voice not recorded";
  return `${words}; ${spoken}.`;
}

function SummaryTab({ view, issues }: { view: VideoStoryView; issues: number }) {
  const { story } = view;
  const total = CLAIM_STATUSES.reduce((sum, status) => sum + story.status_counts[status], 0);
  const sources = Object.entries(story.source_counts);
  const sufficiency = story.problem_statement.sufficiency;
  return (
    <>
      <SectionTitle>Problem statement</SectionTitle>
      <p data-sufficiency={sufficiency}>
        {sufficiency === "documented"
          ? "The repository documents the problem it solves; the statements below are the authors' own."
          : sufficiency === "insufficient"
            ? "Not documented: the repository does not state the problem it solves, and RepoVox did not infer one."
            : "Whether the repository documents its problem was not recorded."}
      </p>
      <ClaimList
        claims={story.problem_statement.claims}
        section="summary-problem"
        empty="No problem-statement claim is recorded."
        compact
      />

      <SectionTitle>Claim status</SectionTitle>
      <ul className="status-breakdown" aria-label="Claims by verification status">
        {CLAIM_STATUSES.map((status) => (
          <li key={status} data-status={status}>
            <Badge state={status} label={story.status_labels[status]} tone={CLAIM_TONES[status]} />
            <span className="status-count">{story.status_counts[status]}</span>
          </li>
        ))}
      </ul>
      <p className="field-hint" data-claim-total={total}>
        {plural(total, "claim")} in total. VERIFIED means the static verifier confirmed the exact
        cited code; INFERRED applies a fixed rule over cited evidence without proving the binding;
        AUTHOR-STATED / NOT VERIFIED BY CODE is what the authors say with no code behind it;
        UNVERIFIED is an assertion or open question nothing supports.
      </p>

      <SectionTitle>Sources read</SectionTitle>
      {sources.length > 0 ? (
        <ul className="source-counts">
          {sources.map(([role, value]) => (
            <li key={role} data-role={role}>
              {SOURCE_LABELS[role] ?? humanize(role)}: <strong>{value}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-hint">No source counts were recorded.</p>
      )}
      <p className="field-hint">
        Files read as data at the pinned commit. RepoVox never runs repository code.
      </p>

      <MismatchInspector />

      {(story.evidence_trimmed || story.instruction_like_lines > 0 || issues > 0) && (
        <>
          <SectionTitle>Disclosures</SectionTitle>
          <ul className="story-disclosures">
            {story.evidence_trimmed && (
              <li data-disclosure="evidence-trimmed">
                Some evidence is shortened in this view: each claim keeps at most 3 citations, and
                quotes longer than 240 characters are clipped and end in &ldquo;...&rdquo;.
              </li>
            )}
            {story.instruction_like_lines > 0 && (
              <li data-disclosure="instruction-like-lines">
                {plural(story.instruction_like_lines, "README line")}{" "}
                {story.instruction_like_lines === 1 ? "reads" : "read"} like instructions addressed
                to an AI model. RepoVox counted {story.instruction_like_lines === 1 ? "it" : "them"}{" "}
                and did not follow or use {story.instruction_like_lines === 1 ? "it" : "them"}.
              </li>
            )}
            {issues > 0 && (
              <li data-disclosure="malformed-entries">
                {plural(issues, "story entry", "story entries")} did not match the story contract:
                malformed entries are left out, and a claim with an unrecognised status is shown as
                UNVERIFIED.
              </li>
            )}
          </ul>
        </>
      )}

      <SectionTitle>Story record</SectionTitle>
      <dl className="definition-list">
        <dt>Repository</dt>
        <dd>{story.repository || "Not recorded"}</dd>
        <dt>Pinned commit</dt>
        <dd>
          {story.commit_sha ? (
            <code className="sha">{story.commit_sha}</code>
          ) : (
            "Not recorded: citations are not linked"
          )}
        </dd>
        <dt>Analysis digest</dt>
        <dd>
          {story.analysis_sha256 ? <code className="sha">{story.analysis_sha256}</code> : "Not recorded"}
        </dd>
        <dt>Versions</dt>
        <dd>
          <code>{story.schema_version}</code> · <code>{story.extractor_version}</code> ·{" "}
          <code>{story.view_version}</code>
        </dd>
        <dt>Narration</dt>
        <dd>{narrationSummary(view)}</dd>
      </dl>
    </>
  );
}

function ProblemTab({ story }: { story: StoryView }) {
  return (
    <>
      <SectionTitle>Problem statement</SectionTitle>
      <ClaimList
        claims={story.problem_statement.claims}
        section="problem_statement"
        empty="No problem-statement claim is recorded."
      />
      <SectionTitle>Problem context</SectionTitle>
      <ClaimList
        claims={story.problem_context.claims}
        section="problem_context"
        empty="The documentation gives no further problem context."
      />
      <SectionTitle>Intended solution</SectionTitle>
      <p className="field-hint">
        What the authors say they built. Each badge says whether analysed code corroborates it.
      </p>
      <ClaimList
        claims={story.intended_solution.claims}
        section="intended_solution"
        empty="The documentation states no intended solution."
      />
    </>
  );
}

const EXPLANATIONS: Record<string, string> = {
  supported: "The analysed source supports an architecture description.",
  unsupported: "The analysed source did not establish an architecture, so none is described.",
  unavailable: "No architecture description is available for this story.",
};

function ImplementationTab({ story }: { story: StoryView }) {
  const architecture = story.architecture;
  return (
    <>
      <SectionTitle>Implementation approach</SectionTitle>
      <ClaimList
        claims={story.implementation_approach.claims}
        section="implementation_approach"
        empty="No implementation-approach claim was established."
      />
      <SectionTitle>Design decisions</SectionTitle>
      <ClaimList
        claims={story.implementation_approach.decisions}
        section="decisions"
        empty="No design decision was established from the source."
      />
      <SectionTitle>System architecture</SectionTitle>
      <p data-explanation={architecture.explanation}>
        {EXPLANATIONS[architecture.explanation] ?? "The architecture outcome was not recognised."}
        {architecture.unavailable_reason && (
          <>
            {" "}
            Reason: <code>{architecture.unavailable_reason}</code>.
          </>
        )}
      </p>
      {architecture.primary && (
        <dl className="definition-list">
          <dt>Primary element</dt>
          <dd>
            <code>{architecture.primary}</code>
            {architecture.view && (
              <>
                {" "}
                · view <code>{architecture.view}</code>
              </>
            )}
          </dd>
          {architecture.architecture_ids.length > 0 && (
            <>
              <dt>Elements</dt>
              <dd>
                {architecture.architecture_ids.map((id, index) => (
                  <span key={id}>
                    {index > 0 && ", "}
                    <code>{id}</code>
                  </span>
                ))}
              </dd>
            </>
          )}
          {architecture.ir_version && (
            <>
              <dt>Report</dt>
              <dd>
                <code>{architecture.ir_version}</code>
              </dd>
            </>
          )}
        </dl>
      )}
      <ClaimList
        claims={architecture.claims}
        section="architecture"
        empty="No architecture claim was established."
      />
      <SectionTitle>Workflow</SectionTitle>
      <ClaimList
        claims={architecture.workflow}
        section="workflow"
        empty="No workflow between architecture elements was established."
      />
      <SectionTitle>Implementation evidence</SectionTitle>
      <ClaimList
        claims={story.implementation_evidence.claims}
        section="implementation_evidence"
        empty="No implementation evidence is recorded."
      />
    </>
  );
}

function OutcomesTab({ story }: { story: StoryView }) {
  return (
    <>
      <SectionTitle>Demonstrated outcomes</SectionTitle>
      <div className="notice outcome-scope" data-tone="warning" role="note">
        <ShieldAlert size={18} aria-hidden="true" />
        <div>
          <p>
            <strong>Tests were read, not run.</strong>
          </p>
          <p data-outcome-scope="">{story.demonstrated_outcomes.scope}</p>
        </div>
      </div>
      <ClaimList
        claims={story.demonstrated_outcomes.claims}
        section="demonstrated_outcomes"
        empty="No outcome is demonstrated by test or example source in this story."
      />
      <SectionTitle>Limitations</SectionTitle>
      <ClaimList
        claims={story.limitations.claims}
        section="limitations"
        empty="The story records no limitation."
      />
      <SectionTitle>Open questions</SectionTitle>
      <ClaimList
        claims={story.unresolved_questions.claims}
        section="unresolved_questions"
        empty="The story records no open question."
      />
    </>
  );
}

function LoadedStory({ view, issues }: { view: VideoStoryView; issues: number }) {
  const { story } = view;
  const base = useId();
  const [tab, setTab] = useState<TabId>("summary");
  const tabs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});
  const focusTarget = useRef<string | null>(null);

  const claims = useMemo(() => claimIndex(story), [story]);
  const locations = useMemo(() => {
    const found = new Map<string, Section>();
    for (const section of SECTIONS)
      for (const item of section.claims(story)) if (!found.has(item.id)) found.set(item.id, section);
    return found;
  }, [story]);
  const mismatchesByClaim = useMemo(() => {
    const index = new Map<string, ClaimMismatch[]>();
    const add = (id: string, entry: ClaimMismatch) => index.set(id, [...(index.get(id) ?? []), entry]);
    for (const mismatch of story.mismatches) {
      for (const id of mismatch.stated_claim_ids) add(id, { mismatch, role: "stated" });
      for (const id of mismatch.evidence_claim_ids) add(id, { mismatch, role: "evidence" });
    }
    return index;
  }, [story]);

  const claimAnchor = useCallback(
    (section: string, claimId: string) => `${base}-claim-${domId(section)}-${domId(claimId)}`,
    [base],
  );
  const mismatchAnchor = useCallback((id: string) => `${base}-mismatch-${domId(id)}`, [base]);

  // Moves focus once the tab holding the target has rendered.
  useEffect(() => {
    const target = focusTarget.current;
    if (!target) return;
    focusTarget.current = null;
    const element = document.getElementById(target);
    element?.scrollIntoView?.({ block: "center" });
    element?.focus({ preventScroll: true });
  });

  const context = useMemo<StoryContextValue>(
    () => ({
      story,
      claims,
      mismatchesByClaim,
      claimAnchor,
      mismatchAnchor,
      showClaim: (claimId) => {
        const section = locations.get(claimId);
        if (!section) return;
        focusTarget.current = claimAnchor(section.key, claimId);
        setTab(section.tab);
      },
      showMismatch: (mismatchId) => {
        focusTarget.current = mismatchAnchor(mismatchId);
        setTab("summary");
      },
    }),
    [story, claims, mismatchesByClaim, claimAnchor, mismatchAnchor, locations],
  );

  const counts: Record<TabId, { value: number; noun: string }> = {
    summary: { value: story.mismatches.length, noun: "mismatches" },
    problem: {
      value: SECTIONS.filter((s) => s.tab === "problem").reduce((n, s) => n + s.claims(story).length, 0),
      noun: "claims",
    },
    implementation: {
      value: SECTIONS.filter((s) => s.tab === "implementation").reduce((n, s) => n + s.claims(story).length, 0),
      noun: "claims",
    },
    outcomes: {
      value: SECTIONS.filter((s) => s.tab === "outcomes").reduce((n, s) => n + s.claims(story).length, 0),
      noun: "claims",
    },
  };

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.findIndex((item) => item.id === tab);
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % TABS.length
        : event.key === "ArrowLeft"
          ? (index - 1 + TABS.length) % TABS.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? TABS.length - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    const id = TABS[next].id;
    setTab(id);
    tabs.current[id]?.focus();
  }

  return (
    <StoryContext.Provider value={context}>
      {story.problem_statement.sufficiency === "insufficient" && (
        <div className="notice story-undocumented" data-tone="warning" role="note" data-problem="undocumented">
          <BookOpen size={18} aria-hidden="true" />
          <div>
            <p>
              <strong>This repository does not document the problem it solves.</strong>
            </p>
            <p>
              RepoVox did not infer or invent a problem from the repository&apos;s name or
              description, so this story states none.
            </p>
          </div>
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Story sections">
        {TABS.map((item) => {
          const selected = item.id === tab;
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
              data-tab={item.id}
              onClick={() => setTab(item.id)}
              onKeyDown={onTabKey}
            >
              {item.label}
              <span className="tab-count" data-tone={item.id === "summary" && count.value > 0 ? "warning" : undefined}>
                <span className="visually-hidden">, </span>
                {count.value}
                <span className="visually-hidden"> {count.noun}</span>
              </span>
            </button>
          );
        })}
      </div>
      {TABS.filter((item) => item.id !== tab).map((item) => (
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
        className="tab-panel story-panel"
        role="tabpanel"
        id={`${base}-panel-${tab}`}
        aria-labelledby={`${base}-tab-${tab}`}
        tabIndex={0}
        data-panel={tab}
      >
        {tab === "summary" && <SummaryTab view={view} issues={issues} />}
        {tab === "problem" && <ProblemTab story={story} />}
        {tab === "implementation" && <ImplementationTab story={story} />}
        {tab === "outcomes" && <OutcomesTab story={story} />}
      </div>
    </StoryContext.Provider>
  );
}

/**
 * The story for the active video. States other than a loaded story are calm and truthful:
 * explainers and older walkthroughs simply have no story; an integrity failure is an alert;
 * a network or server error can be retried without touching playback.
 */
export function StoryExplorer({
  video,
  state,
  expired,
  walkthrough,
  onRetry,
  onShowWalkthrough,
}: {
  video: Video;
  state: StoryState;
  expired: boolean;
  /** The job's walkthrough, when it is another (unexpired) video in this job. */
  walkthrough: Video | null;
  onRetry: () => void;
  onShowWalkthrough: (id: string) => void;
}) {
  const titleId = useId();
  const jump = walkthrough && walkthrough.id !== video.id && (
    <div className="actions">
      <button type="button" onClick={() => onShowWalkthrough(walkthrough.id)}>
        Show the repository walkthrough and its story
      </button>
    </div>
  );
  let body;
  if (expired)
    body = (
      <p className="notice" data-tone="neutral" role="status" data-story="expired">
        This video has expired, so its story is no longer available.
      </p>
    );
  else if (state.status === "loaded") body = <LoadedStory view={state.view} issues={state.issues} />;
  else if (state.status === "loading")
    body = (
      <p role="status" className="field-hint" data-story="loading">
        Loading the problem-to-solution story…
      </p>
    );
  else if (state.status === "corrupt")
    body = (
      <div data-story="corrupt">
        <ProblemNotice problem={state.problem} />
        <p className="field-hint">
          The stored story did not match its recorded integrity digest. RepoVox refuses to show a
          story it cannot verify; the video itself is unaffected.
        </p>
      </div>
    );
  else if (state.status === "malformed")
    body = (
      <div data-story="malformed">
        <ProblemNotice
          problem={{
            message: "The story response could not be read, so RepoVox does not show it.",
            code: "story_malformed",
            status: 200,
          }}
          onRetry={onRetry}
        />
      </div>
    );
  else if (state.status === "error")
    body = (
      <div data-story="error">
        <ProblemNotice problem={state.problem} onRetry={onRetry} />
        <p className="field-hint">Playback is unaffected; only the story could not be loaded.</p>
      </div>
    );
  else
    body = (
      // `idle` (a video kind that never carries a story) and `not-available` read the same.
      <div className="notice" data-tone="neutral" role="status" data-story="not-available">
        <div>
          <p>
            {video.category === "walkthrough"
              ? "No structured problem-to-solution story is available for this walkthrough. It was published before stories were recorded, or RepoVox could not establish a story from verified evidence and narrated the grounded walkthrough instead."
              : "This video carries no problem-to-solution story. The structured story is attached to the job's repository walkthrough."}
          </p>
          {jump}
        </div>
      </div>
    );
  return (
    <section className="story-explorer" aria-labelledby={titleId} data-video={video.id}>
      <div className="story-header">
        <h4 id={titleId}>Problem-to-solution story</h4>
        <p className="field-hint">
          What the repository states, what its analysed source shows, and where they disagree.
          Read from one pinned commit as data; nothing was run.
        </p>
      </div>
      {body}
    </section>
  );
}
