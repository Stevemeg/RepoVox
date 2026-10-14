# ADR-0015: Canonical source facts and qualified static bindings

Status: Proposed for independent engineering review; scoped persistence change owner-authorized

Date: 2026-10-14

## Context

The owner authorized Phase 2C-C remediation after independent review of the
AI-audited exploratory comparison. That historical comparison had 84 reference
facts, 795 predictions and zero exact identity matches. Different parser-rule
vocabularies, import representations, relationship levels and entrypoint rules
prevented pairing. This is not a measurement of zero semantic accuracy.
All references remain partial. No historical reference, prediction or comparison
is revised by this decision.

## Decision

Introduce additive `source-fact-2.0` and analysis envelope `2.3`, with
`static-rules-v2`. Preserve the `source-fact-1.0`, `gold-evaluation-1.0`, official
corpus and exploratory contracts and the accepted scorer unchanged. The exact
legacy analysis 2.2 reader and schema remain available. Future independent
annotations must explicitly select their fact version; there is no automatic
v1-to-v2 reference translation and no fuzzy matching.

The [canonical specification](../development/canonical-facts.md) distinguishes
source semantics from extractor provenance. Repository, snapshot, original file
hash, source ranges, import members/bindings, relationship kinds, dispatch and
resolution classification remain identity-bearing. Only parser-rule labels and
support ordering are non-semantic. Different supported ranges are not normalized
away. This intentionally prefers unmatched facts over unproven equivalence.

Enrich static parsing with conservative lexical bindings, local member import
resolution, inheritance, lexical calls and constructors. Preserve the original
module-level graph alongside qualified edges. Recognize distinct packaging,
library, type, plugin and command candidates without asserting execution.
Declarative configuration citations use original property spans; duplicate keys
are rejected. Re-extraction verifies the new canonical projection from original
source bytes before accepting generated static claims.

## Persistence constraint

The accepted `rv.finish_analysis` function hardcodes artifact schema 2.2 and
rules v1. Its rows are immutable. Writing a 2.3 body through that function would
mislabel provenance. The separately owner-authorized additive completion function must
record truthful versions and reject mixed-version jobs; existing procedures,
historical rows, RLS and fencing must remain intact. No database change is
silently included in the versioning decision. See the
[decision packet](../delivery/phase2c-c-contract-decision.md).

## Consequences

New output requires explicit 2.3 readers. Legacy validation does not rerun old
analysis using new rules. No production deployment or automatic rollout is
authorized. The synthetic tests establish deterministic engineering behavior,
not independent accuracy or official EVAL-ENTRY acceptance. Unsupported binding
patterns remain unresolved. The independent reviewer must assess both positive
and ambiguity controls before engineering acceptance.

Related: [ADR-0010](0010-phase2-static-analysis-boundary.md),
[ADR-0012](0012-independent-gold-contract.md),
[ADR-0014](0014-ai-audited-exploratory-track.md).
