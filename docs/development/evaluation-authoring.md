# Gold-label authoring handbook

Version `gold-authoring-1.0`, 2026-10-12. [Accepted contract](evaluation-gold.md) · [Review checklist](evaluation-review-checklist.md) · [Appointment](evaluation-reviewer-packet.md) · [Preparation schema](../ai/eval-entry-preparation.schema.json).

Preserve `gold-evaluation-1.0`, `source-fact-1.0` and `evaluation-corpus-2.0`. The separate
`eval-entry-preparation-1.0` packet supplements admission evidence without changing
the accepted scorer or ingestion/parsing/PKM/orchestration. Draft labels are partial
until actual scope review finishes. Complete pairing is required by the scorer;
it is not human approval or independent PASS.

1. Acquire only an individually rights-approved pinned scope using the existing secure
   intake. Keep source and source manifest in `<custodian>/<family-id>/source` and its
   adjacent `source_manifest.json`. Do not install/run submitted dependencies or code.
   Review original bytes, not README statements or analyzer verdicts.
2. Preparer independently assigns IDs and records symbols/functions/classes and their
   original file hash, LF-inclusive line range, language, kind, extraction rule and
   relevant parameters/import alias/import name/binding/dispatch attributes. Record
   entry declarations with path/rule/target and actual citations; candidates are not
   executed entrypoints. Empty arrays must be explicitly authored, not missing.
3. Write qualified static edges with canonical source/target identities, relationship,
   classification, support, supported flag and precise citations. Verify anchors and
   relation entailment manually. A syntactic call or dynamic registry cannot establish
   an actual runtime path. Do not fabricate a cross-language call from architectural
   proximity. Supported graph gold and inferred relationships are separate assertions.
4. Independently author each claim ID, exact expected assertion, expected verification
   status, typed atomic fact, original citations and pinned repository SHA. The text
   is a gloss; do not hide runtime/security/purpose predicates in a syntax atom. Cite
   real contradictory/negative evidence for unsupported claims. Broader execution
   stories, doc/source conflicts, expected abstentions and unresolved behavior go in
   separately reviewed semantic expectation/rubric evidence, not ungrounded syntax gold.
5. Record uncertainty and insufficient evidence explicitly. Source paths/hashes/ranges
   must exist; the expected absence of an invented function does not permit citing an
   invented path. Scope completeness includes all facts that the locked scorer must
   pair, while independent authoring must precede viewing predictions. If new predictions
   reveal unannotated scope, mark scoring INCOMPLETE and follow a reviewed new-version
   policy; never copy predictions into gold to produce matching coverage.
6. Validate schemas, source bytes, duplicates and review worksheet; have the actual
   appointed human check all rows and source. Keep preparer/reviewer provenance and
   row decisions outside Git. Rejected/partial/disputed annotations cannot enter freeze.

Offline interfaces (all label outputs in the approved POSIX custodian):

```text
uv run python tools/phase2_corpus.py PRIVATE_MANIFEST --action validate-labels --family FAMILY_ID --source PRIVATE_SOURCE
uv run python tools/phase2_preparation.py --worksheet PRIVATE_FAMILY_JSON --output PRIVATE_STORE/worksheet.json
uv run python tools/phase2_contracts.py --check
```

Worksheet creation produces null decisions and null identities; it never preselects
approval or supplies claims. Its returned protected key names an immutable file, and
rows refer to the independently authored IDs. Edit a new private draft copy to record
decisions; retain prior bytes. The human writes the final receipt; mechanical tools
validate it and cannot authenticate a signature by themselves.

`annotation_digest` seals **every** Family field except the review wrapper, including
source, claims/statuses, symbols, entries, graph, rights, split, derivatives, screening
and adversarial IDs. The receipt lists every claim and edge exactly once. Missing,
conflicting, self-approved or edited labels fail freeze. Changing source/rights/split/
labels after approval invalidates the digest; do not silently rehash approvals.
