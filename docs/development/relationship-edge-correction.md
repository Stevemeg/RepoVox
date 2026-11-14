# Relationship edge correction: `duplicate_canonical_fact` on same-line support

Status: implementation record, 2026-11-14. Not independently reviewed or accepted; the
change touches the accepted analyzer and must not be merged without independent approval.
Related: [analysis](analysis.md), [architecture explainer](architecture-explainer.md).

## Reproduction

A two-file repository where `train.py` contains
`from models import Discriminator, Generator` and `models.py` defines both classes was
rejected at Stage 7 with `duplicate_canonical_fact`
(`tests/fixtures/analysis/member_imports`, test
`test_reported_failure_reproduces_without_the_correction`).

## Root cause

The duplication does not come from parsing, binding annotation or collection validation.

1. **Parsing is correct.** The parser emits one import symbol per member. Both are anchored
   at the whole import statement and differ by imported-member identity.
2. **Edge construction emitted one edge per supporting symbol.** `graph.infer` produced two
   `imports` edges `train.py -> models.py`, one per member symbol. `relationships.py` did
   the same for two calls to one local function on a single line (`calls_lexically`).
3. **Canonical projection cannot tell such edges apart.** A relationship fact is identified
   by subject, target, relationship, classification and support citations, and citations
   are line-level (`path`, `file_sha256`, `start_line`, `end_line`). Two edges whose
   supports sit on the same lines project to byte-identical facts.
4. **Collection validation correctly rejected the collision.**

## Correction

`graph.merge_indistinguishable` runs once after all edges are built. Edges that share
source, target, relationship, classification, rule, qualification and the same set of
line-level anchors become one edge whose `support_ids` list every supporting symbol.

- Imported members keep their own symbols, syntax facts, claims and `imports_symbol` edges.
- No evidence is removed: the merged edge's claim cites the evidence of every supporting
  symbol.
- Duplicate detection, the canonical fact schema, the projection and the verifier are
  unchanged. A forged or split merged edge is rejected by the verifier.

## Compatibility impact

- Only edge groups that previously collided are merged, and any repository containing such
  a group previously failed analysis. For every input that used to pass, edges, edge
  identifiers, canonical facts, claims and counts are byte-identical
  (`test_existing_accepted_facts_are_unchanged`).
- The rule version string `static-rules-v2` is unchanged. Newly accepted repositories carry
  merged edges whose identifier is derived from the sorted support list.
- Evaluator contracts, scoring, the pilot control plane and SQL are untouched.

## Remaining limit, deliberately not masked

`from models import helper, helper` (the same member written twice in one statement) makes
the parser emit the same symbol twice. That is a genuine identity collision and is still
rejected. Resolving it needs member-level byte anchors in the parser, which would change
accepted symbol identities for all imports.
