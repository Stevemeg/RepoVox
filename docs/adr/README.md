# Architectural decisions

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
