# Phase 2C-D independent evaluator review handoff

Review the exact draft PR head on `phase2/source-fact-v2-evaluation`, stacked on
`phase2/canonical-fact-remediation` at accepted commit
`9557938f69f0c71f124abe4633089e531e753693`. Actual PR/CI links belong in the PR body
and completion report; pending checks are not a claimed pass.

Start with [ADR-0016](../adr/0016-independent-source-fact-v2-evaluation.md), the
[normative contract](../development/evaluation-v2.md),
[future blind protocol](../development/evaluation-v2-blind-protocol.md), and
[verification evidence](phase2c-d-verification.md).

Use the [32-case adversarial matrix](../development/evaluation-v2-test-matrix.md)
to locate the positive, negative, unknown and tampered fixtures. Public code:
[source validation](../../apps/api/repovox/evaluation/v2.py),
[scoring and aggregation](../../apps/api/repovox/evaluation/scoring_v2.py),
[prediction projection](../../apps/api/repovox/evaluation/projection_v2.py), and
[custody protocol](../../apps/api/repovox/evaluation/custody_v2.py).

Published contracts: [reference](../ai/gold-evaluation-2.0.schema.json),
[prediction](../ai/evaluation-prediction-2.0.schema.json),
[score](../ai/evaluation-score-2.1.schema.json), and
[aggregate](../ai/evaluation-aggregate-2.1.schema.json).

Independently inspect:

1. Exact canonical equality with no parser-rule/ID dependence, no erased support
   sets and no fuzzy pairing. Review unpaired diagnostics separately from metrics.
2. Manually specified synthetic reference fixtures, meaningful non-equivalence,
   negative verdicts, type-only/dynamic/ambiguous facts and undefined denominators.
3. The prediction adapter's claim/ledger/evidence binding, original analysis hash,
   unprojected runtime text, and entrypoints remaining unreviewed without a ledger.
4. Independent source-only reference validation, excluded ranges, UTF-8 original
   bytes, immutable reference hashes, source packet consistency and revision lineage.
5. Strict partial-scope handling; unknowns cannot become false positives or true
   negatives. Complete structural pairing still requires independent review.
6. Report recomputation, micro-aggregation, duplicate/mixed-version/cross-tenant
   rejection and retention of each family's limitations and commitments.
7. Event ordering, actual capture bytes, A/B commitments, pre-reveal source checks,
   exclusive reservations, permission boundaries and explicit authentication limits.
8. The unchanged production 2.2/2.3 schemas, v1 evaluator, official manifests, no
   historical rescore and no new database migration or dependencies.

Use the public synthetic tests and source diff; private historical packets are
unnecessary. Report defects with independent minimal synthetic reproductions.
Passing tests is machinery conformance under tested conditions, not repository
accuracy, human-reviewed gold, production certification or new-pilot approval.

## C-02/C-03/C-04 re-review

Review the corrective follow-up to `ce703aa349d13d615391bea16241df33d49bd664`;
the draft PR body records the exact corrective head and final-head CI. Run
`uv run pytest tests/unit/test_evaluation_v2_corrections.py -q` and inspect its
source-only synthetic expectations. Verify the 1-of-100 overlap versus undefined
precision, known unsupported/unknown denominators, weighted micro-aggregation,
empty evidence at ordinary/EOF/UTF-8/zero-file boundaries, valid original ranges,
and complete post-reveal pairing remaining diagnostic-only. Mixed-family
aggregates must preserve this limitation and disagreements; descendants cannot
relabel post-reveal lineage as source-only. The explicit archival 2.0 readers
preserve original report interpretation but cannot enter corrected aggregation.
The legacy 2.0 schemas remain unchanged. See the verification report's correction
section for before/after evidence, commands and actual outcomes.
