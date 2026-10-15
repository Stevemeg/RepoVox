# Independent source-fact 2.0 evaluation specification

Version: `exact-v2-1.0`. Status: proposed for independent review, 2026-10-15.
This is offline AI_AUDITED_EXPLORATORY infrastructure. It cannot admit official
gold, freeze splits, authenticate a human review or certify production accuracy.

## Inputs and version boundary

| Contract | Purpose |
| --- | --- |
| `evaluation-source-scope-2.0` | Tenant/family, repository/full SHA, owner binding, permitted original files/hash/language/byte windows, rights and acquisition evidence commitments |
| `gold-evaluation-2.0` | Independently authored canonical assertions, expected verdicts, entailment judgments, partial/complete scope, limitations, provenance and revision lineage |
| `evaluation-prediction-2.0` | Previously committed facts, copied ledger verdicts or explicit unknowns, original analysis hash, engineering commit and projection version |
| `evaluation-score-2.0` | Exact alignment rows, integer counts, ratios, unknowns, commitments, completeness and unpaired diagnostics |
| `evaluation-aggregate-2.0` | Micro-count totals, constituent report commitments and per-family completeness |

Published schemas are named after these versions under `docs/ai/`. Schema shape,
cross-field validation, original-byte validation and semantic review are separate
requirements. JSON duplicate keys/nonfinite constants are rejected. Packet input
is capped at 100 MB; selected source at 50 MB, each file at 5 MB. The source
manifest must already have passed authorized acquisition, filtering and rights
review. This evaluator does not acquire, unpack or execute source.

The trusted operator supplies independently retained scope and packet hashes.
Rights and snapshot proof bytes must exist and match their commitments. Those
proofs document prior rights/pinned-acquisition decisions; a hash is not a new
legal determination or independent authentication of GitHub. A fabricated scope
plus fabricated proofs is not legitimate evaluation input. Future owner approval
must inspect those records before handoff. Source checks verify all selected
complete-file hashes against that approved scope, including files not cited.

## Identity versus judgment

Use the accepted [canonical specification](canonical-facts.md) unchanged.
`identity()` excludes only parser-rule provenance and sorts the exact support
set; `fact_key()` SHA-256 hashes those deterministic identity bytes. Repository,
commit, file checksum, UTF-8 byte offsets, inclusive lines, category, qualified
names, members, aliases/bindings, dispatch, endpoint, relationship, classification
and entrypoint target remain meaningful. Matching never uses annotation IDs,
text similarity or a reduction of the identity fields.

`Judgment` contains independently assigned ID, fact, expected status, evidence
entailment (`supported`, `unsupported`, `unreviewed`) and rationale. The assertion
means only the canonical static fact. Prose rationale cannot broaden its meaning
into a runtime promise. Free semantic/runtime assertions go in `observations`,
with original byte citations and `SEMANTIC REVIEW REQUIRED`; atomic matching does
not certify them. A reviewer may mark a source-anchored relationship unsupported
without claiming its hash-valid location entails that relationship.

| Status | Meaning |
| --- | --- |
| `verified` | Reference: independently supported canonical source assertion. Prediction: an existing ledger verdict with an exact validated binding. Neither means successful runtime execution. |
| `inferred` | Qualified inference or unresolved interpretation; not a verified implementation/runtime assertion. |
| `documentation_only` | Statement about documentation, without establishing implementation behavior. |
| `unsupported` | Explicitly assessed assertion lacks the claimed support. It requires cited reasoning, not absence from a partial reference. |
| `unreviewed` | Expected judgment or prediction verdict is unavailable; correctness is unknown. |

The independent reference does not consume analyzer output. Its permitted inputs
are original source, approved scope/rights, source-only A, opaque B commitment,
original captured response and independently written annotations. The authoring
validator accepts no prediction payload, analyzer claim IDs or suggested answers.
Parser provenance labels in independently written facts can use a reviewer rule
label; they are not expected to imitate analyzer rules.

## Prediction verdict projection

`projection_v2.project_analysis` accepts an immutable analysis 2.3 verify envelope.
It validates tenant-owner/snapshot binding, unique claims, ledger coverage,
claim/ledger status/rule/evidence agreement, recomputed ledger counts, version
metadata, original evidence anchors and the
canonical subject inventory. It reconstructs only a prediction-side association
between declared symbols/edges and facts. It never authors an expected verdict.

The documented static assertion grammar is checked exactly. An unrecognized
runtime sentence cannot inherit a syntax verdict. Such claims remain separately
listed as unprojected; the associated fact has `unreviewed` status. Entrypoint
facts lack ledger claims and therefore remain unreviewed. A selected symbol maps
to one candidate only if unique; otherwise selection is explicitly ambiguous.
Even an `executable_application` candidate is static guard syntax, not an executed
application. No default verified status is derived from parser success.

For real projected inputs, the scorer requires retained original analysis bytes
and recomputes the adapter to detect changes in projected statuses, evidence or
facts. The production verifier's verdict is the prediction being tested, not the
gold authority. Synthetic verdicts are explicitly marked and rejected in future
pilot scopes. This phase generates no actual pilot predictions.

## Source and annotation validation

References and predictions bind to the same tenant, family, repository, full
commit and exact scope bytes. Every endpoint/support citation must lie within
selected scope and use the complete original-file checksum. Byte ranges must be
UTF-8 boundaries with matching original inclusive line numbers. Line-only support
must fit fully selected lines; a partial-byte window cannot authorize an entire
excluded line. Symlinked source paths/ancestors and paths escaping source are
rejected. All source is secret-screened without execution.

Missing support, duplicate facts or IDs, invalid enums/categories, wrong target
structure, excluded citations, source changes and mixed-version records fail
closed. A mathematically valid range does not establish semantic entailment.
Invalid inputs raise validation errors and produce no apparently successful score.
Consequently, citation-validity counts in emitted reports describe validated
inputs only; invalid/missing citation counts are zero after this gate, not an
estimate of the rate in rejected/raw analyzer submissions.

Original response and source-only attestation bytes are required. They establish
retained evidence, not provider identity. Revisions require a predecessor hash,
consecutive revision number, reason, retained owner-approval evidence and source
citations; original A/B bindings cannot change. `revision_context` distinguishes
`initial_blind`, `source_only_correction` and `post_reveal_correction`; reports
retain it. Approval evidence is owner-attested, not an authenticated signature.
Preserve every predecessor and report. Never edit approved bytes.

## Metrics and completeness

Each exact pair has one gold assertion and one prediction. Other rows retain the
complete unmatched fact and its own ID. Duplicate identities reject the input.

| Metric | Numerator / denominator or count |
| --- | --- |
| Matching coverage | Exact pairs / gold; exact pairs / predictions, separately |
| Verdict correctness | Equal known statuses / matches with both statuses known |
| False verified predictions | Predicted verified on an exact match whose known expected status is not verified |
| False-verification rate | False verified / matched verified predictions with known gold judgment |
| Matched verified | Every exact pair with a verified prediction, including unknown gold; the separate reviewed-verified count supplies the false-verification denominator |
| Verified recall | Both verified on exact pairs / all reference verified assertions |
| Unsupported rejection recall | Both unsupported on exact pairs / all reference unsupported assertions |
| Unscored predictions | Unmatched predictions plus matches with either verdict unknown |
| Unscored verified | Verified predictions without a known matching judgment; unprojected verified claims are separately counted |
| Graph/syntax/entrypoint correspondence | Exact matches to supported annotations / predictions and / supported annotations, respectively |
| Missing/additional structure | Set differences against supported reference subset; additional does not mean false positive |
| Evidence entailment | Supported/unsupported independent judgments on exact pairs; other predictions remain unreviewed |
| Unscored reference observations | Retained semantic/runtime observations; never dropped or promoted to atomic correctness |

Zero denominators yield JSON `null`. Percentages are never averaged. Verdict
histograms include all five statuses. Source commit/hash/range/scope checks are
mandatory before scoring. The full rows provide missing/additional symbol,
relationship and entrypoint identities. One-field classification, category or
entrypoint-target differences are unpaired diagnostics requiring independent
review, not confirmed error counts. Ambiguous diagnostic correspondence is
omitted rather than arbitrarily paired. Exact matching remains unchanged.

Pairing is COMPLETE only for complete annotation scope, a nonempty 100% pairing
in both directions, known verdicts/evidence judgments, no unprojected claims and
no reference observations awaiting semantic review.
Any failure makes formal acceptance INCOMPLETE, including perfect pairing to a
partial reference. Once complete, verdict disagreement gives REJECTED; otherwise
acceptance is REVIEW_REQUIRED. No status is an independent PASS. Completeness is
relative to declared scope, never implicitly the whole repository.

Reports recompute counts, ratios, alignment completeness and diagnostics on
validation. Aggregation verifies each retained report hash/version and recomputed
content, rejects duplicate families/snapshots and cross-tenant inputs, sums integer
counts and recomputes ratios. An incomplete family makes the aggregate incomplete;
rejected and review-required families remain visible. Empty aggregates are rejected.

## Independence and shared code

| Shared code | Why permitted |
| --- | --- |
| `analysis.facts.CanonicalFact`, `identity`, `semantic_symbol` | Reviewed schema and deterministic representation; no source extraction or expected verdict generation |
| `evaluation.gold` scalar/citation/strict-record types | Existing validation primitives, with no v1 conversion |
| `evaluation.scoring.symbol_statement` | Published static assertion grammar used only in the prediction adapter, not expected-answer authority |
| `analysis.contracts` | Read-only 2.3 envelope validation on prediction side |
| Privacy screening/redaction and preparation DAC check | Security controls, not semantic correctness judgments |

The evaluator never imports/calls the parser, graph resolver or production verifier
to determine correctness. An import-guard regression detects those dependencies.
Reference fixtures are manually specified independently from production output;
adapter tests separately exercise synthetic real analysis as predictions.

All 2.2/2.3 production schemas, v1 evaluation modules, official manifests and
historical packets remain unchanged. No implicit v1/v2 conversion is provided.
See [future protocol](evaluation-v2-blind-protocol.md) and
[verification report](../delivery/phase2c-d-verification.md).
