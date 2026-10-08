# ADR-004: Fargate CPU and ECS GPU EC2 hosting

Status: proposed · Date: 2026-10-08

Context: PaaS simplifies solo operations; untrusted parsing/rendering requires enforceable network/IAM/resource isolation.

Decision revised: ECS Fargate **CPU** frontend/API/analysis/TTS/render, ECS on GPU EC2 for private Director inference, and separate research/training account. RDS/Redis/Cognito/S3/ALB/ACM retained; us-east-1/budget pending approval. Fargate itself does not provide GPU acceleration. One warm L4-class replica initially; no inference HA claim.

Alternatives: dedicated Runpod Secure Cloud GPU with CPU SaaS reduces hourly costs but needs private tunnel/region/data-control parity; private dedicated GPU VM + CPU VPS lowers fixed expense while owner handles patching/backups/failover. Original Render CPU-only design cannot supply the complete Director GPU architecture. Selected AWS option simplifies same-region isolation at higher idle/network expense.

Consequences: GPU quotas/inventory, drivers, model load/readiness, warm idle expense and release rollback capacity added to gates. No paid AI API fallback. Revisit GPU provider on measured economics/control parity; scale-to-zero only after cold-start/deadline tests and owner approval. Multi-region deferred.

Evidence: [comparison](../operations/deployment.md#hosting-comparison), [AWS ECS network guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html).
