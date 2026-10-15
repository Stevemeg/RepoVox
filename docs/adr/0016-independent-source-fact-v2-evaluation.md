# ADR-0016: Independent source-fact 2.0 evaluation

Status: Proposed for independent evaluator review. Date: 2026-10-15.

The owner accepted Phase 2C-C at `9557938f69f0c71f124abe4633089e531e753693`
and authorized an additive evaluator, not another pilot. The accepted canonical
contract emits facts separately from the production verification ledger.
Entrypoint facts have no corresponding verdict claim. Parsing cannot fill that gap.

Define `gold-evaluation-2.0`, `evaluation-prediction-2.0`, `evaluation-score-2.0`
and `evaluation-aggregate-2.0`, plus source-scope, blind-source and custody-event
contracts. Keep every v1 evaluator, official gate and production schema unchanged.
No implicit conversion, database migration or new acquisition is introduced.

Independent references contain original source identities, separately authored
expected statuses/evidence judgments and explicit provenance. Opaque A/B hashes
bind the handoff without revealing predictions. Original reference bytes are
retained; corrections use explicit predecessor commitments and source citations.

Share the accepted canonical schema and identity algorithm, never extraction or
production verification as an independent correctness authority. The separate
`analysis-2.3-verdict-projection-1.0` adapter checks sealed claim/ledger/evidence
bindings and copies existing statuses. Unsupported grammar and missing verdict
links remain unreviewed/unprojected. The scorer recomputes this adapter from the
committed original analysis bytes for real prediction packets.

Match complete canonical identities exactly. Do not erase ranges, support sets,
aliases, targets or classifications. One-field category differences can be shown
as explicitly unpaired diagnostics; they never affect matching or correctness.
Micro-aggregate integer counts; retain partial scope, unmatched facts and unknown
statuses. Structural completeness can yield REVIEW_REQUIRED, never independent
PASS. Invalid source or commitments stop comparison rather than entering ratios.

Reuse the existing POSIX custodian checks. New content-addressed exclusive files,
tenant checks and sequenced hash-linked events preserve bytes and detect edits.
These controls are not administrator-proof WORM or provider authentication.
Actual future rights, storage and blind-pilot authorization remain prerequisites.

Consequences: exact matching can miss source-equivalent representations beyond
the accepted normalization. Runtime/semantic statements stay outside atomic
scoring. Source provenance checks cannot decide entailment or legal ownership.
Synthetic conformance tests do not establish repository accuracy. Rollback stops
the offline v2 tooling; no application or database rollback is needed.

See the [normative specification](../development/evaluation-v2.md),
[future blind protocol](../development/evaluation-v2-blind-protocol.md),
[verification](../delivery/phase2c-d-verification.md), and
[review handoff](../delivery/phase2c-d-reviewer-handoff.md).

## Independent review corrections C-02/C-03/C-04

Date: 2026-10-15. Emit score/aggregate 2.1 with scorer `exact-v2-1.1`.
Keep the original 2.0 report schemas and explicit archival readers; no automatic
conversion or new legacy scoring. Rename supported-overlap ratios as diagnostic
fractions and calculate independently reviewed precision only when every predicted
assertion in its category has an explicit known independent judgment. Micro-count
aggregation preserves unavailable denominators.

Reject empty evidence windows and semantic endpoint spans at evaluation boundaries
and original-source checks, preserving production canonical schema/identity and v1.
Post-reveal corrections carry diagnostic-only eligibility, remain INCOMPLETE and
cannot qualify as new blind results. Aggregates propagate this restriction, and
lineage cannot return from post-reveal to source-only context. Disagreement metrics
and original predecessor commitments remain available for independent adjudication.
