# Architectural decisions

Independent cloud-retention design: [ADR-0021](0021-independent-cloud-retention.md),
mock-only preparation; no paid deployment or real-pilot authorization.

Post-execution custody: [ADR-0020](0020-post-execution-custody-authority.md), proposed
for independent review; no real-pilot activation or official corpus acceptance.

Phase 2 proposals: [ADR-0010 static boundary](0010-phase2-static-analysis-boundary.md)
and [ADR-0011 parser isolation](0011-parser-process-isolation.md).
Phase 2 review corrections: [ADR-0012 independent gold/pairing](0012-independent-gold-contract.md).

All proposed for Phase 0 review, dated 2026-10-08. Acceptance follows independent validation; exact dependency/model versions require later compatibility checks.

| ADR | Decision |
| --- | --- |
| [001](0001-modular-architecture.md) | Modular backend and separate process roles |
| [002](0002-durable-jobs.md) | PostgreSQL truth, outbox and fenced leases |
| [003](0003-evidence-and-isolation.md) | Static evidence and untrusted input isolation |
| [004](0004-hosting.md) | Fargate CPU + ECS GPU EC2, separate research |
| [005](0005-provider-and-render-boundaries.md) | Self-hosted Director/TTS and trusted rendering |
| [006](0006-director-ownership.md) | Model authority and base/data/adapter ownership |
| [007](0007-model-promotion.md) | Training/evaluation promotion gates |
| [008](0008-gpu-serving.md) | Warm private GPU serving and isolated training |
| [009](0009-local-object-storage.md) | Local Phase 1 S3-compatible storage choice; production architecture preserved |
| [013](0013-eval-entry-preparation-evidence.md) | Phase 2B preparation evidence, sealed human review and protected freeze supplement |
| [014](0014-ai-audited-exploratory-track.md) | Separate blind AI exploratory source review; no official counts or human approval |
| [015](0015-canonical-source-fact-semantics.md) | Additive canonical source semantics, qualified static bindings and truthful artifact versioning |
| [016](0016-independent-source-fact-v2-evaluation.md) | Independent v2 references, exact scoring, unknown verdicts and private blind custody |
| [017](0017-pilot-control-plane-safety.md) | Durable pilot authorization, fenced cancellation and mandatory original-file scope |
| [018](0018-isolated-retention-runtime.md) | Isolated runtime identity, executable bytes and bounded retention readiness |
| [019](0019-growing-evaluation-custodian.md) | Durable growing evidence, write-intent recovery and fenced expiry |
| [020](0020-post-execution-custody-authority.md) | Separate execution leases and bounded owner-key custody review grants |
| [021](0021-independent-cloud-retention.md) | External immutable registry, cleanup fencing, reconciliation and honest cloud guarantees |
| [022](0022-aws-retention-integration.md) | Deployment-disabled AWS adapters, conditional registry and independent service verification |
| [023](0023-sdk-certificate-trust-boundary.md) | Upstream CA removal and fail-closed, explicitly selected SDK trust |
