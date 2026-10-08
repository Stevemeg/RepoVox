# ADR-004: ECS Fargate initial hosting

Status: proposed · Date: 2026-10-08

Context: PaaS simplifies solo operations; untrusted parsing/rendering requires enforceable network/IAM/resource isolation.

Decision: ECS Fargate in us-east-1 pending owner approval, RDS PostgreSQL, ElastiCache Redis, Cognito, S3, ALB/ACM and Secrets Manager. Per-job tasks, VPC endpoints and restricted proxy for fixed acquisition/provider destinations; no EKS.

Alternatives: Render containers/managed Postgres/Redis + S3/Cognito is simpler, but deny-by-default egress/per-task IAM requires additional design beyond basic PaaS. VPS/Compose cheaper but owner handles patching/isolation/backups. ECS costs more fixed networking/HA but provides explicit controls.

Consequences: infrastructure-as-code, network tests and restore drills before launch; network/backup costs included. Revisit Render if equivalent controls demonstrated; multi-region deferred.

Evidence: [comparison](../operations/deployment.md#hosting-comparison), [AWS ECS network guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html).
