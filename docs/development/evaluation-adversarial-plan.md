# Adversarial variant preparation plan

Version `adversarial-plan-1.0`, 2026-10-12. [100 planned slots](../ai/evaluation-adversarial-plan.json) · [Gold workflow](evaluation-authoring.md) · [Storage](evaluation-storage.md).

There are **100 planned slots, zero materialized official variants and zero approved
variants**. The slots spread five cases across each of twenty future held-out parent
families; parent IDs remain null until approved sources exist. Plans, existing security
fixtures and generated mutations do not count as independently reviewed variants.
Select seven Python, seven JS/TS and six mixed parents after real approval; rotate case
categories across language/size/complexity rather than testing a single template.

The structured plan covers twenty categories: README contradiction, fake architecture,
ambiguous imports, unresolved calls, renamed symbols, misleading comments, invented
functions, forged locations, invalid commit references, incomplete source, multiple
entrypoints, malformed source, unsupported language, prompt injection, secret canaries,
suspicious configuration, oversized source, nested content, stale hashes and forged
verification labels. Each category appears in five planned cases. A human independently
specifies the exact mutation and expected behavior before inspecting analyzer/Director
results; generated output never supplies its own expectation.

For each variant, preserve parent family and SHA, versioned recipe, original/mutated
manifest hashes, exact scope, outcome (`qualified_extraction`, `abstention` or
`intake_rejection`), source-grounded expectations/rubric, preparer/reviewer IDs, independent
receipt and adjudication. `VariantReview` checks reviewed evidence and exact materialized
bytes in `<family>/variants/<variant-id>/source`. Invalid SHA/location inputs are
the **test stimulus**, not invalid gold provenance: gold still cites the valid parent
or mutation's real evidence. Secret cases use trusted synthetic non-credential canaries;
never introduce real credentials. Malformed/unsupported/oversized content may correctly
fail intake; do not force extraction or treat an unrun safety observation as a pass.

Design expected abstention precisely: distinguish safe intake rejection, qualified
static extraction, unsupported assertion rejection and insufficient-evidence refusal.
Contradicted README must not become verified source truth; ambiguous calls may retain
call syntax while refusing target/runtime claims. Injection strings are untrusted data;
no tool execution, instruction adoption or exfiltration is permitted. Fake verification
labels cannot upgrade status. Independent humans judge actual semantic expectations;
deterministic source/hash checks do not prove entailment.

Batch A tests only workflow mechanics using synthetic fixtures. Batch C measures real
specification/materialization/review time. Batch D scales to 100 **approved** variants
across at least twenty approved held-out parents. Variants/revisions never inflate family
counts or cross splits. Keep sources and answers private, register any later final run,
and do not run Director/model experiments during Phase 2B.
