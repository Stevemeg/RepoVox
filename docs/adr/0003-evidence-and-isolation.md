# ADR-003: Static evidence, never execute submitted code

Status: proposed · Date: 2026-10-08

Context: repository content is adversarial; docs/static graphs can mislead.

Decision: bounded GitHub archive pinned to SHA, safe regular-file inspection without checkout/install, Tree-sitter parsing and evidence-linked claims. Label inference; deny executable model output and repository assets. Acquisition/parsing/provider/render task profiles have separate permissions.

Alternatives: running repositories enriches traces but violates policy/expands risk; README-only is unreliable; regex lacks structure; language servers may run project plugins. Static analysis provides auditability with explicit runtime uncertainty.

Consequences: dynamic paths remain unverified, some projects fail evidence gates. Citation presence does not prove entailment; rules and independent human audits must check it. Execution requires a separately approved future product/threat model, never a convenience exception.

Evidence: [pipeline](../architecture/pipeline.md), [security](../security/threat-model.md).
