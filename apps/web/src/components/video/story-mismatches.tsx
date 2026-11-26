"use client";
import { useContext, useId } from "react";
import { AlertTriangle } from "lucide-react";
import { ClaimReferences, MISMATCH_KINDS, mismatchKind, StoryContext } from "./story-claims";

/*
 * Mismatches are first-class (frontend handoff section 3, rule 2): every entry is listed in
 * full, never behind a collapsed toggle, each with its kind, its own detail text and the
 * stated and evidence claims it names, resolved against the story.
 */

const KIND_HELP: Record<string, string> = {
  readme_only_feature: "The documentation describes a feature that no analysed code implements.",
  mention_only_technology: "A technology is mentioned in the documentation but not used by analysed code.",
  declared_only_technology: "A dependency is declared, but no analysed source uses it.",
  unstated_implementation: "The code uses something the documentation does not mention.",
  incomplete_implementation: "Code exists for a stated feature, but it is a placeholder.",
  unbenchmarked_performance_claim: "A performance claim has no benchmark source behind it.",
  unsupported_architecture_claim: "An architecture claim is not supported by the analysed source.",
};

export function MismatchInspector() {
  const context = useContext(StoryContext);
  const titleId = useId();
  if (!context) return null;
  const { story, mismatchAnchor } = context;
  const mismatches = story.mismatches;
  return (
    <section className="mismatches" aria-labelledby={titleId} data-count={mismatches.length}>
      <h5 id={titleId} className="story-section-title">
        <AlertTriangle size={16} aria-hidden="true" />
        Mismatches
        <span className="count-badge" data-tone={mismatches.length > 0 ? "warning" : "neutral"}>
          {mismatches.length}
          <span className="visually-hidden"> {mismatches.length === 1 ? "mismatch" : "mismatches"}</span>
        </span>
      </h5>
      {mismatches.length === 0 ? (
        <p className="notice" data-tone="neutral" data-mismatches="none">
          No mismatches were detected: RepoVox&apos;s fixed checks found no disagreement between
          what this repository states and what its analysed source shows.
        </p>
      ) : (
        <>
          <p className="field-hint">
            Where what the repository states and what its analysed source shows disagree. Every
            mismatch is listed.
          </p>
          <ol className="mismatch-list">
            {mismatches.map((mismatch) => (
              <li
                key={mismatch.id}
                id={mismatchAnchor(mismatch.id)}
                tabIndex={-1}
                className="mismatch"
                data-kind={mismatch.kind}
              >
                <div className="mismatch-head">
                  <span className="mismatch-kind">{mismatchKind(mismatch.kind)}</span>
                  <code className="mismatch-code">{mismatch.kind}</code>
                </div>
                <p className="mismatch-detail">{mismatch.detail}</p>
                {MISMATCH_KINDS[mismatch.kind] && KIND_HELP[mismatch.kind] && (
                  <p className="field-hint">{KIND_HELP[mismatch.kind]}</p>
                )}
                <div className="mismatch-sides">
                  <div>
                    <h6 className="mismatch-side-title">What is stated</h6>
                    <ClaimReferences
                      ids={mismatch.stated_claim_ids}
                      empty="No stated claim: the documentation says nothing about this."
                    />
                  </div>
                  <div>
                    <h6 className="mismatch-side-title">What the evidence shows</h6>
                    <ClaimReferences
                      ids={mismatch.evidence_claim_ids}
                      empty="No evidence claim: no analysed code corroborates what is stated."
                    />
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
