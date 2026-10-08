# Production deployment design

Proposed configuration, 2026-10-08; **nothing deployed/provisioned**. [Architecture](../architecture/overview.md) · [Reliability](reliability.md) · [Cost assumptions](cost-model.md) · [Phase gates](../delivery/roadmap.md)

## Hosting comparison

| Strategy | Deployable components | Strengths | Costs/limitations |
| --- | --- | --- | --- |
| Render PaaS + AWS objects/auth | Next.js/FastAPI containers, background workers, managed Postgres/Redis; S3/Cognito | Few platform tasks, container support, simple releases | Always-on large render instances idle at low volume; equivalent egress/task-role isolation requires extra design. Cross-provider latency/egress and private network configuration. [Render offerings](https://render.com/pricing) accessed 2026-10-08; exact prices not verified from dynamic page. |
| AWS ECS Fargate (selected) | Frontend/API services, dispatcher/proxy, bounded worker tasks, RDS/ElastiCache/S3/Cognito/ALB | Explicit SG/VPC endpoint/IAM boundaries, per-task sizing, no Kubernetes, managed DB | Higher fixed HA/network cost, infrastructure-as-code and AWS operations burden; Chromium sandbox/task behavior requires staging validation. [Fargate pricing/configuration](https://aws.amazon.com/fargate/pricing/) accessed 2026-10-08. |

VPS/Compose is an additional lower-cost alternative, rejected initially because owner would maintain host patching, sandboxing, backup and failover. Selected region **us-east-1** is a proposal for coherent compute/storage pricing, not an assumption about legal/data-residency suitability. Owner must approve region/budget before provisioning.

## Environments and launch components

| Environment | Configuration / separation |
| --- | --- |
| Development | Local containers planned for Postgres/Redis/S3 emulator, mock auth/LLM/TTS and small synthetic fixtures; no real provider keys. Explicit dev-only mocks cannot deploy to production. No such containers implemented in Phase 0. |
| Staging | Separate AWS account preferred, isolated VPC/buckets/identity pool/secrets/DB; same image digests/migrations/contracts as production at smaller size. Synthetic public fixtures only; capped paid evaluation after authorization in later phase. |
| Production | Separate account/roles/domain, private multi-AZ network, two frontend and two API replicas behind HTTPS ALB; one dispatcher (replica-safe leases), one restricted egress proxy service; RDS PostgreSQL Multi-AZ, managed Redis primary/replica with failover, S3 and Cognito. |

Initial compute sizing: frontend/API replicas each 0.5 vCPU/1 GiB, dispatcher 0.25 vCPU/0.5 GiB; egress proxy 0.25 vCPU/0.5 GiB. DB starting `db.t4g.small` Multi-AZ, 20 GiB gp3 (final adequacy measured), Redis starting `cache.t4g.small` primary+replica (confirm engine/region support before provisioning). Not benchmark-backed recommendations; load tests may require changes. Fixed production capacity deliberately larger than development and includes no free tier.

Network: public ALB only; frontend/API/workers/DB/Redis in private subnets across two AZs. SG restricted by role; DB/Redis not internet accessible. S3 gateway endpoint; ECR/logs/Secrets Manager endpoints for needed roles, or managed NAT to proxy where required. Workers needing internet use explicit HTTP CONNECT/HTTPS allowlisted proxy; SG denies direct internet routes. NAT, endpoint, proxy and ALB charges budgeted. TLS to managed DB/Redis; inbound API limited ALB/BFF. Verify proxy DNS/IP policies and no bypass in staging. [AWS network guidance](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-network.html) supports role-separated network controls; actual policy evidence remains a launch gate.

Domain owned by product owner, DNS to ALB, ACM certificate, HTTPS redirect/HSTS; exact app domain undecided. Private S3 origin read only by API/worker roles. Browser gets signed API delivery grant ≤5 min, not S3 URL; API streams validated byte ranges after reserving delivery bytes, sets attachment headers for download and caps concurrent streams. No CDN initially. [AWS presigned URL behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html) motivates rejecting direct bearer S3 delivery for strict cost quotas. Outbound API bandwidth is counted in the cost model; same-region S3 origin transfer pricing must be rechecked before launch.

Secrets Manager stores provider/DB/signing secrets, distinct per environment; least privilege ECS task roles, no secrets in Git/images/CI output. Use IAM task roles for S3, GitHub Actions OIDC for deployment with account/branch/environment constraints; no long-lived AWS key in CI. Key rotation and credential revocation runbook tested later.

## Worker profiles and resource limits

One backend worker image can have different ECS task definitions/roles per stage class, not new services with independent databases. Dispatcher polls durable readiness, reserves global slots and starts bounded tasks; Celery consumes stage notifications, validates DB lease and exits after assigned work/idle timeout. Concurrency DB reservation + task ID reconciler prevents launch storms or duplicate task-start ambiguity. Worker heartbeat/paid work semantics remain [data model rules](../architecture/data-model.md#idempotency-delivery-and-recovery).

| Profile | CPU / memory / scratch | Egress/permissions |
| --- | --- | --- |
| Acquisition | 1 vCPU / 2 GiB / 20 GiB | Proxy GitHub allowlist; assigned job S3 prefix and restricted stage ledger, no model keys. |
| Static parsing | 1 vCPU / 2 GiB / 20 GiB | No internet; DB/queue/S3 endpoints only, no provider credentials. Untrusted parser runs as non-root, image read-only, no install/import paths. |
| AI orchestration | 1 vCPU / 2 GiB / 20 GiB | Sanitized committed snippets only; provider allowlist via proxy, job budget/operation role, no raw archive processing. |
| Render/encode | 4 vCPU / 8 GiB / 20 GiB | No internet, job-scoped S3 inputs/outputs, restricted stage ledger. Chromium receives no secrets, bundled templates/local assets only. |

Fargate includes 20 GiB ephemeral capacity; application scratch hard cap 2 GiB analysis / 10 GiB render, separate from image/system space. Stop task on overflow; intermediate chunks uploaded/removed incrementally. Maximum launch two analysis-class jobs and two render-class jobs, one job/task, Chromium page concurrency two and FFmpeg threads two. CPU/memory cannot exceed task specification. Source/archive limits in PRD and stage/job timeouts in data model. Per-file parse watchdog 5s. Cancellation termination 60s. Signed task IAM/S3 session scope must not be inferred from a client owner ID.

Chromium sandbox must work on the selected task image/platform with no unsafe `--no-sandbox` fallback. If Fargate compatibility tests cannot satisfy this, render hosting is blocked pending a reviewed isolated VM/container alternative and cost update. Do not claim undocumented Linux capabilities or namespace controls are available in Fargate.

## Migrations, CI/CD and release promotion

Future implementation: owner-authored infrastructure-as-code and Alembic migrations, not manual undocumented provisioning. Phase 0 introduces no cloud configuration or deploy workflows.

1. PR checks: docs/links/contracts, appropriate code tests in later phases, secret/vulnerability/license checks, format/type checks. Automation read-only toward Git history; no bot commits. Independent validation then owner-controlled merge.
2. Build immutable signed/digest-pinned images and SBOM once; staging deploy those digests with mock/pilot config. GitHub OIDC environment permissions narrowly scoped; no production secrets in fork PR jobs.
3. Before migration: backup/restore point, compatibility check, migration lock, no mixed app versions requiring incompatible schema. Use expand/contract: add nullable/backfilled fields first; old code still works. One controlled migration task, never per-container startup races.
4. Staging gates: security/recovery/media/quality/load tests, budgets, alerts and restore drill. Owner approves promotion of same images/migrations/config version to production environment.
5. Rolling API/frontend deploy behind health checks; pause new worker admission, drain/reconcile active jobs, retain old template/worker versions for in-flight artifact contracts, then promote. Re-enable admission after smoke checks/queue health. Kill switch blocks paid sends throughout failed release.

## Backup, restore and rollback

RDS automated backups/PITR retained 35 days; daily encrypted snapshots and monthly restore drill. Target DB RPO ≤1 hour/RTO ≤4 hours measured including incident response. S3 versioning for accidental overwrite recovery, lifecycle and all-version deletion required; final objects immutable/checksummed, deletion ledger outside restored DB checkpoint prevents resurrecting removed access. Redis snapshots optional convenience; restore work from PostgreSQL, not Redis correctness. Disaster restore also verifies objects/identity mappings/usage unknown charges and reconciles due jobs before provider calls resume.

Rollback order: disable admission/paid sends, drain/revoke leases of affected version; redeploy prior image/config compatible with expanded schema; keep new schema if compatible. Do not blindly run destructive down migration. If incompatible corruption, restore to a separate DB at pre-migration point, reconcile later writes/usage/deletions, owner accepts recovery-point loss, swap endpoint and reconcile jobs. Corrupt render/template outputs unpublished/tombstoned, prior template retained. Region-wide outage handled by restore/manual redeploy plan with stated RTO risk; active-active multi-region deferred.

## Retention and deletion

Normative proposed policy, owner approval pending. Retention is per artifact creation/terminal time as noted, not an unlimited cache.

| Data | Retention / cleanup |
| --- | --- |
| Extracted/source archive/scratch | Delete after terminal state, or latest 24h from acquisition; never keep raw source for 30-day cache. Worker crash/orphan cleaner daily and at task exit. Retry may reacquire exact SHA if still public. |
| Intermediate PKM/redacted evidence/storyboard/narration/audio | 30 days from terminal state; bounded to 10 MiB average structured data, audio separately accounted. No raw provider payload dumps. |
| MP4/captions/evidence sidecar | 30 days from publication, expiry clearly shown. Expired objects and all versions removed within 24h. History remains with “expired” label. |
| Job history/sanitized attempt errors | 90 days after terminal state; idempotency key retained for same period. |
| Auth sessions/refresh credentials | Idle 24h/max 7d; revoke on logout/deletion; expired/revoked rows and encrypted credentials removed within 24h. Redis session cache not authoritative. |
| Usage/cost minimum ledger | 365 days, no source/text; account deletion pseudonymizes retained accounting entries, access revoked immediately. Legal requirements reviewed before launch. |
| Logs/traces/security audit | 30 days redacted logs/traces; 90 days access/security audit; 35-day encrypted DB backups. No signed URLs/secrets/content. Delivery grant rows removed 24h after expiry, aggregated byte usage retained with cost ledger. |

Project/account deletion sets tombstone transactionally, revokes grants/work immediately, cancels active jobs and queues cleaner. Live object versions/metadata/identity sessions deleted within 24h; account identity removed/revoked after job settlement obligations recorded. Backups naturally expire in ≤35 days; restores apply external deletion suppression ledger before exposure. Minimal pseudonymous deletion suppression IDs kept through backup lifetime. Cleaner retries/alerts on overdue deletion; billing uncertainty does not justify retaining source/video. Media route checks revocation on each range request and at ≤5s chunk boundaries; already transferred files cannot be revoked.

## First launch versus later scale

Launch needs HTTPS/session security, private objects, resource isolation, durable jobs/quota, migrations, CI gates, restore/rollback, basic logs/metrics/alerts and owner incident runbooks. Defer CDN, active-active/multi-region, sophisticated autoscaling, Kubernetes, data warehouse, team roles, subscription billing and advanced editing. At 10k videos/month, increase bounded concurrency after benchmark/cost review and database/Redis sizing checks; architecture does not grant automatic phase expansion.
