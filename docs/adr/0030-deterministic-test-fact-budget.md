# ADR-0030: Deterministic test-fact budget

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `fix/github-sha-and-ml-weights` (draft PR #21), following
[ADR-0029](0029-prose-path-names-and-oversized-syntax-facts.md). Related:

- [ADR-0025 problem-to-solution story](0025-problem-to-solution-engineering-story.md)
- [static analysis notes](../development/analysis.md)
- [PRD limits](../product/prd.md)

The following are unchanged:

- `Limits.facts` is still 10,000, and the analysis artifact contract stays at
  `schema_version` `2.3`.
- Core migrations stay at `0004` and the media database at `m001`.
- `Settings.fail_closed`, `AGENTS.md`, `docs/ai/`, and the Stage 2 secret and archive rules.
- Every other bound: 10,000 facts in one file, the parser's node and time bounds, the
  1,024-character fact text cap, and the 20,000-claim cap.

## Context

ADR-0029 let `Stevemeg/Synthetic-Data` at `0c71c556` pass Stages 1–3 and parse both long
expressions. Stage 4 then failed `analysis_fact_limit` on the repository-wide cap.

Measured on the local mirror of that tree, with this branch, the counts are:

- **Structural facts:** 12,173 in total.
- **Non-test facts:** 8,168, plus 16 context facts.
- **Test-file facts:** 4,005 in total:
  - 3,121 calls;
  - 540 imports, together with base references bound to them;
  - 344 others: modules, test functions and classes, decorators and main guards.

The mirror differs from the tree only in the six scrubbed test-credential lines.

The non-test code fits the cap comfortably. What overflows it is mostly call sites inside test
bodies. No claim and no story scene rests on those individual calls.

## Decision

### 1. Test-file facts are dropped in fixed tiers, only above the cap

`repovox.analysis.budget.FactBudget` holds every fact of the parsed files in arrival order,
followed by the context facts. A fact belongs to a test file when Stage 3 classified its path
as `test`. That means a `tests`, `test` or `__tests__` directory, a `test_` prefix, `.test.`
or `.spec.`, or a `_test.py` suffix.

- **At or under the cap,** every fact is kept and the output is byte-identical to before.
- **Above the cap,** test-file facts are dropped tier by tier, while the total still
  exceeds the cap:
  1. call facts;
  2. import facts, together with any fact whose lexical target is one of those imports (a
     base class bound to an import), so no kept fact names a dropped one;
  3. every remaining test-file fact.
- **Non-test facts** (source and context) are never dropped. If they alone exceed the cap,
  `analysis_fact_limit` is raised exactly as before, as soon as that is certain.

The rule depends only on the bytes and the manifest order. Stage 4 and the Stage 9 verifier
apply it to the same re-parsed bytes, so Stage 9 reconstructs the same symbols. Because
counts only grow, a tier is released as soon as it must be dropped. The budget therefore
never holds more than the cap plus one file's facts. Without that, a repository with huge
test files could exhaust the parser sandbox's memory before reaching the same decision.

### 2. Disclosure without changing schema 2.3

The 2.3 `Structure` contract has no field for omitted facts. The disclosure therefore uses
values in fields that already exist:

- **Manifest reason.** Each parsed test file that lost at least one fact has its free-text
  `reason` set to `parsed_test_calls_omitted`, `parsed_test_calls_imports_omitted` or
  `parsed_test_facts_omitted`, according to the repository's tier. Its `status` stays
  `parsed` and its bytes still count toward coverage: the file was parsed without errors.
- **Knowledge limitation.** Stage 7 appends one line to `knowledge.limitations`, for example:
  `Test-fact budget: the repository exceeded the 10,000-fact analysis cap, so call facts
  from 37 test files were omitted; their test definitions and imports were kept. The budget
  omitted no source-file fact.` It is shown with the other limitations in the analysis panel.
- **Stage 9 check.** The verifier rejects the artifact with `insufficient_evidence` unless
  the manifest records exactly the files its own re-extraction omits and the limitation line
  matches. A hidden or an invented budget fails closed.
- **Story statement.** The story extractor states the budget as the first open question.
  It is an `unresolved`, `UNVERIFIED` claim with no citation, like the runtime scope
  statement, and reads, for example: `The analysis exceeded its 10,000-fact cap, so call
  facts from 37 test files were omitted; their test definitions and imports were kept.`
  `verify_story` fails `story_budget_mismatch` unless that statement matches the verified
  manifest.
- **Limitations scene.** The scene always says the statement, just before the runtime
  sentence. When tier 3 ran, the story does not claim that the repository has no tests.

The story schema and extractor versions are unchanged. For any analysis the budget did not
touch, the story output is identical. Before this ADR, a budgeted analysis could not exist:
Stage 4 failed.

### 3. Two contract fixes found on the same repository

These are separate commits, each with its own regression test,
`tests/unit/test_type_only_imports.py` and `tests/unit/test_story_caps.py`:

- **Type-only import marker.** A TypeScript `import type {...}` fact kept the parser's
  private `_type_only` marker. In `bindings.annotate`, `any(...) or s.pop(...)` skipped the
  pop, and the strict 2.3 `Symbol` contract rejected the Stage 4 payload. The marker is now
  always removed, and `syntax.type_only` keeps the same value.
- **Story caps.** The extractor took 24 implementation-evidence claims where the
  `problem-to-solution-1.0` schema allows 16. It also let an intended solution cite a
  corroborating claim that a cap later cut, which failed with `story_invalid`. It now takes
  16, and a corroborating claim counts only if it survives its cap. The same kept set
  filters mismatches. Any story that was valid before is unchanged.

## Security and truthfulness

| Concern | Effect |
| --- | --- |
| Hidden truncation | None. The manifest, the knowledge limitations, the story and the video all state the omission. The verifier rejects any disagreement. |
| Production evidence | Never dropped. A repository whose non-test code exceeds the cap still fails closed. |
| Misclassified source | A source file under a `tests/` path is treated as a test file. Its facts can be dropped only above the cap, and the disclosure names the number of affected files. |
| Claims | Claims rest only on emitted facts. Analysis is less complete above the cap, but never asserts more. |
| Resources | Retained facts stay bounded by the cap plus one file. The per-file bound and the parser's node and time bounds are unchanged. |
| Story wording | The new story templates add their words to the fixed vocabulary that non-documentary claims are checked against. |

## Consequences

- `Stevemeg/Synthetic-Data` passes Stage 4 at tier 1. The mirror gives:
  - **Stage 4:** 9,068 facts. That is 8,184 non-test facts, all kept, and 884 test-file
    facts. Call facts were omitted from 37 test files.
  - **Stage 7:** 17,639 claims.
  - **Stage 9:** 11,094 claims verified, 6,536 inferred, 9 documentation-only and 0
    unsupported.
- **JavaScript and TypeScript tests.** Tests declared as `test(...)` or `it(...)` calls lose
  those call facts at tier 1. The story therefore cannot cite them as demonstrated outcomes.
  Python `def test_*` functions and test classes remain.
- **Test-to-source calls.** Test-file call relationships, such as `calls_lexically` edges
  and test framework constructions, are not reported above the cap. Test imports and their
  resolved import edges are kept at tier 1.
- **Other limits.** A repository between the fact cap and the claim cap can still meet the
  unchanged 20,000-claim cap.

## Rollback

Revert the commits. No migration, stored artifact or schema version changes. An artifact
produced with the budget would then fail Stage 9 re-verification, because the reverted verifier
rebuilds every test fact. A story with the budget statement would fail its wording check.
Such jobs fail closed.

## Tests

`tests/unit/test_test_fact_budget.py` covers:

- the tier order and the import closure;
- arrival order kept at or under the cap;
- each tier dropped only while the total exceeds the cap, and memory released early;
- a repository under the cap and one exactly at the cap, both byte-identical to the facts
  emitted before this ADR;
- four JavaScript test files with 12,000 calls plus a Python test, with these results:
  - the run passes Stages 3–9 at the real cap;
  - every production fact is kept and no test-file call is kept;
  - test definitions and imports remain;
  - the manifest reasons and the limitation line are exact;
- repeated runs, which give identical payloads;
- the verifier rejecting a hidden budget, a relabelled file and an invented budget;
- the story statement, its place in the Limitations scene, and a forged story without it,
  which fails `story_budget_mismatch`;
- production facts over the real cap, and over a smaller one, which still fail
  `analysis_fact_limit`;
- tiers 2 and 3, end to end, with no kept fact naming a dropped one.
