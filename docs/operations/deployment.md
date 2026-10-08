# Production deployment design

Revised proposal, 2026-10-08; **nothing provisioned/deployed, no GPU purchased**. [Architecture](../architecture/overview.md) | [Director](../ai/director-architecture.md) | [Speech](../ai/speech-strategy.md) | [Reliability](reliability.md) | [Costs](cost-model.md)

## Hosting comparison

| Strategy | Deployable separation | Strengths | Limits and decision |
| --- | --- | --- | --- |
| AWS Fargate CPU + ECS on GPU EC2 (selected) | CPU web/API/ingestion/TTS/render, private GPU gateway/vLLM EC2 capacity provider, separate training account | Private network/IAM/region/object flow, familiar durable jobs; managed DB/auth; no Kubernetes | GPU host/AMI/driver patching and idle expense, availability/quotas not guaranteed. Fargate itself has no GPU acceleration. [ECS GPU docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html), [G6](https://aws.amazon.com/ec2/instance-types/g6/), accessed 2026-10-08. |
| Runpod Secure Cloud dedicated GPU container + CPU SaaS | Own pinned gateway/vLLM on dedicated Pod, or private authenticated serverless worker; CPU AWS services over constrained private tunnel | Lower GPU list rates, managed GPU lifecycle; self-hosted weights/engine, not paid third-party model API | Region/inventory/private-tunnel/DPA/retention need evidence, cross-cloud egress and secrets, ephemeral cold starts. [Pricing](https://www.runpod.io/pricing): L4 Pod $0.49/h, serverless group $0.69/h accessed 2026-10-08; not reserved availability quote. Alternative only after control parity verified. |
| Lower-cost VPS + private dedicated GPU VM | CPU app/DB/queue on patched VPS, one dedicated A40-class GPU Pod/VM behind WireGuard tunnel; private objects/auth retained | Smaller CPU footprint, possible 48GB GPU at lower hourly rate; realistic low-volume/pilot option | Owner handles host isolation/patching/DB backups/failover and tunnel; no multi-AZ assumption. Estimated CPU $80/mo and GPU $0.49/h, not complete quote. Community/shared anonymous GPU hosts rejected for customer data. |

Selected region us-east-1 is provisional; approve rights/residency/budget and detailed quotes first. Compare warm/idle and scale-to-zero economics in cost model, not only active token cost. No external paid LLM/TTS dependency or silent failover to AI API. Cloud compute hosting remains a paid infrastructure cost.

## Environments and launch components

Development: local mock auth/Director/TTS and synthetic evidence/contracts; optional unchanged-base experiments only in later authorized phase. No model downloads here. Staging separate account/VPC/buckets/identity/DB, same pinned release/images as production; GPU scheduled only for approved evaluation windows, not continuously assumed warm. Production CPU frontend/API replicas behind ALB/ACM, PostgreSQL RDS Multi-AZ, managed Redis primary/replica, Cognito, private S3, dispatcher/proxy. GPU model service in private subnet on ECS GPU EC2, one warm replica initially; TTS and render isolated CPU task definitions. Research/training separate account/subnet/bucket/IAM, no production customer-prefix/DB access.

CPU sizing retained: four frontend/API replicas total each 0.5 vCPU/1GiB, dispatcher and restricted egress proxy each 0.25 vCPU/0.5GiB; initial DB db.t4g.small Multi-AZ/20GiB gp3 and Redis cache.t4g.small primary/replica subject to tests/region support. These are estimates, not benchmarks. GPU candidate g6.2xlarge one NVIDIA L4 advertised 24GB, 8vCPU/32GiB host RAM, 80GiB encrypted model disk; available runtime VRAM lower and must be measured. GPU hourly $1.20 is conservative planning assumption, **not verified AWS regional quote**. ECS task reserves one GPU via EC2 GPU capacity provider/optimized AMI, explicit CPU/memory reservation; no Fargate GPU task.

Networking: public ALB only, private CPU/GPU/DB/Redis, restricted SG role paths and TLS. GPU gateway accepts only orchestration service grant with job/owner/stage/fence/release/expiry; no browser route, public engine/admin port, arbitrary adapter/model/schema upload or inference internet egress. Engine loopback/internal port inaccessible outside authenticated gateway; readiness endpoint private, liveness exposes no prompt/model path. CPU acquisition uses allowlisted GitHub proxy. S3/ECR/logs/Secrets Manager via scoped endpoints; GPU runtime read-only model prefix, no research/customer archive prefix, no registry writer. Approved selected evidence sent encrypted to gateway, ephemeral buffers only; model operations/result pointer in durable backend ledger. Disable prompt logging/telemetry and cross-tenant KV/prefix caching. TTS receives narration only; renderer receives safe scenes/audio.

Domain/HTTPS/session/CSRF and signed metered range delivery unchanged. API reads private S3 origin, never returns raw S3 URL; delivery grants <=5min, atomic owner/video byte reservations, cap streams, tombstone/revocation checks and fixed attachment headers. Secrets Manager holds DB/signing/internal service credentials distinct by environment; no normal AI API keys. Owner-authorized external evaluation secrets restricted to research. GitHub deployment OIDC scoped, no long-lived AWS keys or bot commits.

## Worker profiles and resource limits

| Workload | CPU/GPU/memory/scratch | Network and capacity |
| --- | --- | --- |
| Frontend/API | CPU Fargate as above | ALB/session/authorized DB/S3; media limits in cost policy. |
| Ingestion/static verification | 1vCPU/2GiB/20GiB task, 2GiB app scratch | Two jobs, no paid keys; GitHub only acquisition, parser no internet; source caps/watchdog retained. |
| Director orchestration | 1vCPU/2GiB CPU task | Launch one task per reserved GPU sequence (one initially, three at 10k); queue waits in DB before task start. Calls private gateway after verifying evidence/lease; no direct engine access. |
| Director inference | GPU EC2, one GPU/task; 8vCPU/32GiB host, 80GiB disk | One active sequence/GPU, eight pending requests, one/owner; context/token limits in Director; one warm replica launch. |
| Self-host TTS | 2vCPU/4GiB/20GiB task, 2GiB app scratch | Two tasks, no runtime internet; 240s attempt, narration/voice allowlist. |
| Render/encode | 4vCPU/8GiB/20GiB task, 10GiB app scratch | Two jobs, Chromium pages two/FFmpeg threads two; no internet; sandbox validation still required. |
| Training/evaluation | Separate 48-80GB GPU research profile | Approved licensed data only, bounded GPU-hours/checkpoint storage, no inference/customer network/roles. |

Dispatcher DB slot reservations, stage leases and uncertain task-start reconciliation remain. GPU request admission reserves token/KV/compute capacity separately from analysis/render slots, no task launch per token request. All jobs absolute deadline 45min, GPU attempts/cancellation in data model; source limits retained. Inference runtime health: liveness process; readiness validates signed release/weight/tokenizer/grammar checksums, small **synthetic** schema warm-up request and free-memory margin before admitting jobs. No readiness based merely on open TCP port.

Cold-start assumption: 600s to pull/check/load/warm GPU model; actual time unknown. Readiness timeout 20min, no admissions until warm. Baseline model disk local cached from private hashed registry, 60GiB model archive allowance; read-only mount. At least four reloads/month modelled, load time consumes paid warm hours; no claim of instantaneous serverless restart. One warm host is generation single point of failure: API/history/playback stay available, but queue jobs can expire; no inference HA/SLA claim. Owner may approve warm standby with incremental idle cost or accept bounded pilot risk; staging failure/availability evidence must satisfy targets before commercial launch.

Autoscaling: one warm minimum, approved max three replicas for 10k scenario, each one active sequence; scale from durable GPU queue wait (>60s sustained 5min), measured utilization/memory and forecast budget, never just token count. Budget capacity reservation before EC2 start, GPU quota/inventory failure throttles admission; no infinite retries/paid API fallback. Drain outstanding operations before scale-in. Scale-to-zero not default production: resumed host weight/warm-up delay may consume job deadline and GPUs may be unavailable; alternatives require separate cold-start admission window and revised latency objective. Training cannot borrow production GPU. GPU host/model rollback can need temporary extra capacity, reserve it or pause/drain generation.

Chromium sandbox/egress tests remain launch blockers; no --no-sandbox fallback. If Fargate cannot support safe renderer, reviewed isolated CPU VM alternative and cost update required. No GPU/container/driver test executed in Phase 0.

## Migrations, CI/CD and release promotion

Future implementation: owner-authored infrastructure-as-code and Alembic migrations, not manual undocumented provisioning. Phase 0 introduces no cloud configuration or deploy workflows.

1. PR checks: docs/links/contracts, appropriate code tests in later phases, secret/vulnerability/license checks, format/type checks. Automation read-only toward Git history; no bot commits. Independent validation then owner-controlled merge.
2. Build immutable signed/digest-pinned images and SBOM once; staging deploy those digests with mock/pilot config. GitHub OIDC environment permissions narrowly scoped; no production secrets in fork PR jobs.
3. Before migration: backup/restore point, compatibility check, migration lock, no mixed app versions requiring incompatible schema. Use expand/contract: add nullable/backfilled fields first; old code still works. One controlled migration task, never per-container startup races.
4. Staging gates: security/recovery/media/quality/load tests, budgets, alerts and restore drill. Owner approves promotion of same images/migrations/config version to production environment.
5. Rolling API/frontend deploy behind health checks; pause new worker admission, drain/reconcile active jobs, retain old template/worker versions for in-flight artifact contracts, then promote. Re-enable admission after smoke checks/queue health. Kill switch blocks inference execution throughout failed release.

## Backup, restore and rollback

RDS automated backups/PITR retained 35 days; daily encrypted snapshots and monthly restore drill. Target DB RPO ≤1 hour/RTO ≤4 hours measured including incident response. S3 versioning for accidental overwrite recovery, lifecycle and all-version deletion required; final objects immutable/checksummed, deletion ledger outside restored DB checkpoint prevents resurrecting removed access. Redis snapshots optional convenience; restore work from PostgreSQL, not Redis correctness. Disaster restore also verifies objects/identity mappings/usage unknown charges and reconciles due jobs before model requests resume.

Rollback order: disable admission/inference execution, drain/revoke leases of affected version; redeploy prior image/config compatible with expanded schema; keep new schema if compatible. Model alias rollback uses prior verified base/adapter/quantizer/engine manifest; in-flight jobs retain pinned release, no silent model substitution. Do not blindly run destructive down migration. If incompatible corruption, restore to a separate DB at pre-migration point, reconcile later writes/usage/deletions, owner accepts recovery-point loss, swap endpoint and reconcile jobs. Corrupt render/template outputs unpublished/tombstoned, prior template retained. Region-wide outage handled by restore/manual redeploy plan with stated RTO risk; active-active multi-region deferred.

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

Launch needs private self-hosted Director/TTS with approved model evaluation/license/security, GPU capacity/health/rollback and separate research roles, plus HTTPS/session security, private objects, resource isolation, durable jobs/quota, migrations, CI gates, restore/rollback, basic logs/metrics/alerts and owner incident runbooks. Defer CDN, active-active/multi-region, sophisticated autoscaling, Kubernetes, data warehouse, team roles, subscription billing and advanced editing. At 10k videos/month, increase reviewed GPU and CPU bounded concurrency after benchmark/cost review and database/Redis sizing checks; architecture does not grant automatic phase expansion.

## Model and research artifact retention

Private registry retains current and prior verified releases plus notices/eval lineage while rollback support required; never public by default. Model object allowance 60GiB plus 80GiB encrypted local disk per GPU in costs. Research dataset storage 100GiB initial estimate, immutable versions/access/deletion in training strategy, distinct from 24h customer source/30-day media. Retain candidate training checkpoints <=90 days absent promotion/rights need; prune with dependency manifest. Rights/privacy tombstone withdraws dependent adapters immediately and purges live copies <=24h; clean retraining/evaluation before re-promotion. Dataset manifests/tombstone hashes retained as minimum provenance without deleted source. No backup restore can bypass suppression ledger.
