# ADR-0012: Independent gold contract and source-fact pairing

Status: Proposed for independent Phase 2 re-review. Date: 2026-10-12.

[Gold semantics and metrics](../development/evaluation-gold.md) · [Preparation](../development/evaluation-preparation.md)

R2-01 found that the validated Family could not carry symbols/entrypoints required by
the scorer. R2-02 found that comparing independent IDs to analyzer-generated IDs could
silently score zero pairs. Both findings apply to reviewed SHA `b35d93d`.

Define standalone strict `gold-evaluation-1.0`, inherited by Family, and explicitly
version corpus metadata as `evaluation-corpus-2.0`. Required arrays are authored, not
defaulted. JSON Schema, relational Pydantic validation and original-byte source checks
serve different documented roles. No frozen approval is automatically migrated.

Use `source-fact-1.0` canonical atomic identities and an independently specified narrow
prediction assertion adapter. IDs/verdicts are excluded from identity; source snapshot,
hash/range/attributes and qualification are included. Unknown semantics remain unscored.
Gold expected labels never come from predictions. Ambiguous one-to-many pairing fails
completeness. At least one pair and 100% gold/prediction pairing are required; aggregate
reports propagate incompleteness. No scorer returns acceptance PASS.

Consequences: explicit annotations require more preparer work and re-review, and changed
syntax/rules may need new gold. Broader semantic claims need a reviewed new contract or
human mappings. This favors visible gaps over guessed entailment. Ingestion, parsers,
PKM/verifier, durable orchestration, isolation and approved evaluation targets remain
unchanged. No human appointment, rights approval or corpus freeze is fabricated.
