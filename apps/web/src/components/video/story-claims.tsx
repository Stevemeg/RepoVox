"use client";
import { createContext, useContext } from "react";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/external-link";
import { humanize } from "@/lib/format";
import { safePermalink } from "@/lib/security";
import {
  CANONICAL_STATUS_LABELS,
  CLAIM_TONES,
  type ClaimStatus,
  type StoryClaim,
  type StoryEvidenceRef,
  type StoryMismatch,
  type StoryView,
} from "@/lib/story-types";

/*
 * Claims, status badges and pinned citations. Every repository string (claim text, paths,
 * quotes, ids) becomes a React text node and nothing else. A citation is a link only when
 * `safePermalink(permalink, story.commit_sha)` accepts it, and then only through
 * `<ExternalLink>`; otherwise the page says why the link is withheld.
 */

export type MismatchRole = "stated" | "evidence";
export type ClaimMismatch = { mismatch: StoryMismatch; role: MismatchRole };

export type StoryContextValue = {
  story: StoryView;
  /** Every claim by id. */
  claims: Map<string, StoryClaim>;
  /** The mismatches that name each claim. */
  mismatchesByClaim: Map<string, ClaimMismatch[]>;
  /** A stable DOM id for a claim shown in full in `section`. */
  claimAnchor: (section: string, claimId: string) => string;
  mismatchAnchor: (mismatchId: string) => string;
  /** Shows the claim in its section (switching tab) and moves focus to it. */
  showClaim: (claimId: string) => void;
  /** Shows the mismatch in the summary (switching tab) and moves focus to it. */
  showMismatch: (mismatchId: string) => void;
};

export const StoryContext = createContext<StoryContextValue | null>(null);

function useStory(): StoryContextValue {
  const value = useContext(StoryContext);
  if (!value) throw new Error("Story parts render inside a StoryExplorer.");
  return value;
}

/** A DOM-safe fragment for an untrusted id. */
export const domId = (value: string) => value.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 80);

const EVIDENCE_TYPES: Record<string, string> = {
  author_stated_problem: "Author-stated problem",
  inferred_problem_context: "Problem context",
  intended_solution: "Intended solution",
  implemented_solution: "Implemented solution",
  demonstrated_outcome: "Demonstrated outcome",
  unverified_outcome: "Unverified outcome",
  limitation: "Limitation",
  unresolved: "Open question",
};

/** Proofs are test and example source that RepoVox read and never ran. */
const PROOFS: Record<string, string> = {
  unit_test: "Unit test source, read and not run",
  integration_test: "Integration test source, read and not run",
  benchmark: "Benchmark source, read and not run: it establishes no performance figure",
  example: "Example source, read and not run",
};

export const MISMATCH_KINDS: Record<string, string> = {
  readme_only_feature: "README-only feature",
  mention_only_technology: "Mention-only technology",
  declared_only_technology: "Declared-only technology",
  unstated_implementation: "Unstated implementation",
  incomplete_implementation: "Placeholder implementation",
  unbenchmarked_performance_claim: "Unbenchmarked performance claim",
  unsupported_architecture_claim: "Unsupported architecture claim",
};

export const mismatchKind = (kind: string) => MISMATCH_KINDS[kind] ?? humanize(kind);

/** The literal badge text for a status. Never anything but the contract's four labels. */
export function ClaimBadge({ status }: { status: ClaimStatus }) {
  const { story } = useStory();
  // `status_labels` is normalized to the contract's fixed wording (`normalizeLabels`).
  const label = story.status_labels[status] ?? CANONICAL_STATUS_LABELS[status];
  return <Badge state={status} label={label} tone={CLAIM_TONES[status]} />;
}

/** `path:start-end` of a citation, as text. */
export const citationLabel = (ref: StoryEvidenceRef) =>
  `${ref.path}:${ref.start_line}-${ref.end_line}`;

function Citation({ citation }: { citation: StoryEvidenceRef }) {
  const { story } = useStory();
  const permalink = story.commit_sha ? safePermalink(citation.permalink, story.commit_sha) : null;
  return (
    <details className="evidence">
      <summary>
        <code>{citationLabel(citation)}</code>
      </summary>
      {permalink ? (
        <ExternalLink href={permalink} className="citation-link">
          View these lines on GitHub at commit {story.commit_sha.slice(0, 7)}
        </ExternalLink>
      ) : (
        <p className="field-hint" data-permalink="withheld">
          {story.commit_sha
            ? `No link: this citation's permalink is not a GitHub permalink pinned to commit ${story.commit_sha.slice(0, 7)}, so RepoVox does not link it.`
            : "No link: this story did not record a valid pinned commit, so no citation is linked."}
        </p>
      )}
      {citation.quote ? (
        <pre className="code-block">{citation.quote}</pre>
      ) : (
        <p className="field-hint">No quoted lines were included for this citation.</p>
      )}
    </details>
  );
}

/** Why a claim has no citation, from its status. */
const NO_CITATION: Record<ClaimStatus, string> = {
  VERIFIED: "No citation is included in this view.",
  INFERRED: "No citation is included in this view.",
  DOCUMENTATION_ONLY: "No citation is included in this view.",
  UNVERIFIED: "No evidence supports this statement; it is shown as an open question or assertion.",
};

function ClaimReference({ claimId }: { claimId: string }) {
  const { claims, showClaim } = useStory();
  const claim = claims.get(claimId);
  if (!claim)
    return (
      <li className="claim-ref">
        <span className="field-hint">
          Claim <code>{claimId}</code> is not included in this view.
        </span>
      </li>
    );
  return (
    <li className="claim-ref">
      <ClaimBadge status={claim.status} />
      <span className="claim-ref-text">{claim.text}</span>
      <button type="button" className="button-ghost link-button" onClick={() => showClaim(claim.id)}>
        Show claim<span className="visually-hidden">, {claim.id}, in the story</span>
      </button>
    </li>
  );
}

/** A list of claims by id, resolved against the story (mismatches, corroboration). */
export function ClaimReferences({ ids, empty }: { ids: string[]; empty: string }) {
  if (ids.length === 0) return <p className="field-hint">{empty}</p>;
  return (
    <ul className="claim-refs">
      {ids.map((id) => (
        <ClaimReference key={id} claimId={id} />
      ))}
    </ul>
  );
}

function ClaimItem({
  claim,
  section,
  compact,
}: {
  claim: StoryClaim;
  section: string;
  compact: boolean;
}) {
  const { claimAnchor, mismatchesByClaim, showMismatch } = useStory();
  const mismatches = mismatchesByClaim.get(claim.id) ?? [];
  const proof = claim.proof ? (PROOFS[claim.proof] ?? `${humanize(claim.proof)} source, read and not run`) : null;
  return (
    <li
      className="story-claim"
      id={compact ? undefined : claimAnchor(section, claim.id)}
      tabIndex={compact ? undefined : -1}
      data-status={claim.status}
      data-claim-id={claim.id}
    >
      <div className="story-claim-head">
        <ClaimBadge status={claim.status} />
        <span className="story-claim-type">
          {EVIDENCE_TYPES[claim.evidence_type] ?? humanize(claim.evidence_type)}
        </span>
      </div>
      <p className="story-claim-text">{claim.text}</p>
      {(claim.source_location || proof) && (
        <p className="story-claim-meta">
          {claim.source_location && (
            <>
              Source <code>{claim.source_location}</code>
            </>
          )}
          {claim.source_location && proof && " · "}
          {proof}
        </p>
      )}
      {mismatches.length > 0 && (
        <ul className="mismatch-chips" aria-label="Mismatches that name this claim">
          {mismatches.map(({ mismatch, role }) => (
            <li key={`${mismatch.id}-${role}`}>
              <button
                type="button"
                className="mismatch-chip"
                onClick={() => showMismatch(mismatch.id)}
              >
                {role === "stated" ? "Stated side of a mismatch" : "Evidence side of a mismatch"}:{" "}
                {mismatchKind(mismatch.kind)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {!compact && claim.supports.length > 0 && (
        <div className="story-claim-supports">
          <p className="story-claim-meta">Corroborated by implemented code:</p>
          <ClaimReferences ids={claim.supports} empty="" />
        </div>
      )}
      {!compact &&
        (claim.evidence_refs.length > 0 ? (
          <ul className="evidence-list" aria-label="Pinned citations">
            {claim.evidence_refs.map((citation, index) => (
              <li key={`${citation.id}-${index}`}>
                <Citation citation={citation} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="field-hint">{NO_CITATION[claim.status]}</p>
        ))}
    </li>
  );
}

/**
 * The claims of one story section, each with its literal status badge. `compact` shows the
 * badge and text only (for summaries); the full form adds citations and is the target that
 * "Show claim" moves focus to.
 */
export function ClaimList({
  claims,
  section,
  empty,
  compact = false,
}: {
  claims: StoryClaim[];
  section: string;
  empty: string;
  compact?: boolean;
}) {
  if (claims.length === 0) return <p className="field-hint story-empty">{empty}</p>;
  return (
    <ul className="story-claims" data-section={section}>
      {claims.map((claim, index) => (
        <ClaimItem key={`${claim.id}-${index}`} claim={claim} section={section} compact={compact} />
      ))}
    </ul>
  );
}
