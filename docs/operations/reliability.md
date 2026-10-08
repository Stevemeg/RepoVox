# Reliability and operating procedures

Proposed, 2026-10-08. Targets in [PRD](../product/prd.md#nonfunctional-requirements-and-success-metrics); transitions/retries solely defined in [data model](../architecture/data-model.md). [Deployment/rollback](deployment.md) · [Costs](cost-model.md)

## Observability and alerting

Structured JSON logs: timestamp/severity/service/environment/release/trace ID/job ID/stage/attempt/fence/error code/duration; pseudonymous owner ID only where needed. Do not log raw URLs with tokens, source, prompts, model responses, secrets or signed media links. OpenTelemetry trace context flows API→outbox→attempt→gateway/inference/TTS/render; correlate gateway operation IDs without payload. Sampling must retain errors/security events, avoid high-cardinality job IDs as metric labels.

Metrics: admission/rejection by code, supported success %, queue age/length, stage p50/p95/p99, lease expiration/duplicates, reconciliation backlog, unknown inference operations, tokens/characters/cost vs reservation, render CPU/memory/scratch, MP4 validation failures, DB/Redis latency/errors, URL mint/playback errors, deletion overdue count and backup freshness.

| Alert | Threshold / response |
| --- | --- |
| API unhealthy/error surge | >5% 5xx for 5 min or no healthy replica; owner pager/email, inspect release/dependency, rollback if release-related. |
| Queue/timeout | Oldest admitted stage >5 min or supported-job warm p95 >35 min; throttle admission, inspect resources/leases/GPU health, do not exceed concurrency cap automatically. |
| Worker/quality failures | >10% supported failures over 30 jobs or any ungrounded severe claim in audit; suspend affected stage/template, preserve sanitized evidence, remediate before resume. |
| Cost/abuse | Forecast monthly budget ≥80% warning; ≥100% block new compute admissions. Any job attempts over reserved maximum blocks send; unknown active inference outcomes alert immediately. |
| Security | Any cross-tenant signal, secret egress canary or sandbox/network escape: stop admission/inference/signing, revoke keys if affected, incident response. |
| Cleanup/backup | Any live deletion >24h or no valid backup/restore coverage for RPO >1h; owner alert, retry idempotent cleanup/backup repair, do not declare restore capability without drill. |

Solo owner owns on-call; no implied 24/7 staffed team. 99.5% API objective and 4h restore target need coverage/budget assessment. Alert channels/escalation contact finalized before production, test notification delivery without sharing customer data.

## Incident handling

Severity 1: source/credential/tenant exposure or uncontrolled GPU/infrastructure spending; severity 2: generation outage, object loss or failed restore; severity 3: degraded latency/local quality defect. Record detection/time/release/scope. Stop affected capability with independent admission, inference-send and URL-signing kill switches. Preserve redacted diagnostics and ledger; avoid copying secrets into tickets. Assess impact, rotate secrets/revoke sessions where relevant, rollback per deployment, notify affected users/owner as legally appropriate, verify recovery and document root cause/actions. Security notification obligations/contacts reviewed before launch. No messages or incident systems configured in Phase 0.

## Recovery acceptance tests

Future implementation tests, not executed results. Each needs DB state/assertions and local gateway mock call counts; actual GPU/model evaluation only in a later explicitly authorized phase.

| Failure injection | Required observation |
| --- | --- |
| Duplicate/out-of-order queue deliveries | One active lease/output per stage, no next-stage execution before predecessor, no double quota/cost settlement; invalid owner messages rejected. |
| Worker death before inference send | Expired lease recovered, unique unsent intent reclaimed safely; at most one valid sender under DB guard. |
| Worker death after engine submission before durable response | Unknown active operation blocks replay; recovered validated response/confirmed prior stop permits progression within deadline, else fails safely. No exactly-once inference claim. |
| Worker death after artifact upload / DB commit | Pre-commit orphan removed; committed result reused without new inference call. Stale worker publish/heartbeat fenced out. |
| Cancel races completion | Job row locking yields one terminal outcome; cancellation-first forbids publication/new calls; success-first rejects late cancellation. Task termination ≤60s. |
| Redis full loss or outage | Durable due stages republished/reconstructed; no job/history/quota loss, duplicate processing harmless. |
| DB outage/deadlock | No new inference sends without reservation/valid lease; transaction retries bounded; reconciliation restores correct stages, unknown GPU usage retained. |
| S3 missing/corrupt/partial upload | Hash/probe mismatch blocks success, retries bounded; eventual cleanup does not delete active committed artifacts. |
| Gateway busy/engine OOM/auth/timeout | Retry only known-safe transient failures, Backoff honored within deadline; auth/policy fail permanently, no fallback escalation. |
| Deadline/oversized repo/render hang | Absolute deadline includes queue time; resource caps terminate without corrupting other jobs, stable user-facing code. |
| Restore drill | Fresh isolated DB from PITR within RPO/RTO, deletion ledger applied, objects checked, Redis rebuilt, unknown usage reconciled before inference resume. |
| Deployment rollback | Old image handles expanded schema/contracts, admission drains, in-flight old templates preserved; rollback checks status/playback and owner policy. |
| GPU host loss/unknown abort | Gateway reconciles operation IDs, fences old request, confirms stopped or drains/resets replica before bounded replay; completed durable artifact reused. One warm host loss reduces generation availability; no false success or paid fallback. |
| Bad release/OOM/cold startup | Digest/license/schema warm-up/readiness fails closed, no customer admission until ready; bounded retry and private synthetic probe. Roll back signed alias after drain; jobs remain release-pinned, incompatible revoked jobs fail safely. |
| Training contention/deletion | Research has no production data/queue/IAM access and cannot borrow production GPU; revoked dataset invalidates dependent adapters and backup restoration does not re-promote them. |

## GPU and model operations

Record release/engine/quantizer versions, token prefill/decode aggregate rates, time-to-first-token, warm/cold p95, request occupancy, GPU busy/load/idle hours, VRAM/OOM, admission wait/abort acknowledgment and validation/repair rates. Prompts/token contents never metric labels/log fields. TTS tracks CPU seconds, real sample durations, pronunciation/alignment failures and voice digest; render tracks actual frames/encode CPU. Research hours, dataset versions and promotion scores are isolated from production dashboards.

Alerts: any invalid hash/unauthorized inference attempt or severe factual error blocks affected release; two OOMs/10min drain and investigate, never expand context silently. GPU readiness absent >20min, abort acknowledgment absent >60s, queue wait >5min or warm generation p95 >35min throttle admission/notify owner. Forecast GPU/idle spending >=80% budget warns and >=100% blocks new jobs/scale-out. Replace unready host only within approved capacity; inventory failure is explicit degraded generation, no external AI fallback. One warm replica is not inference HA; owner must accept bounded pilot risk or fund standby before commercial availability promises.

Health probes use synthetic non-customer input; startup validates weight/tokenizer/adapter/license/release digests then schema warm-up. Separate process liveness from readiness, retain prior release files/images for drained rollback. Disable new jobs, stop/reconcile affected requests, restore prior compatible manifest/engine/image, synthetic probe, then resume. Security-revoked in-flight releases fail rather than switching weights mid-job. Data model owns retry maxima/deadlines; no restart loop that bypasses attempts/GPU reservations.

Reliability reports show denominators/exclusions and actual commands/evidence. Every successful video probes codecs/duration/dimensions/size and citations; human audits catch semantic errors schemas cannot. [Roadmap](../delivery/roadmap.md) makes these launch gates explicit. No GPU, fault-injection, media or deployment tests executed in Phase 0.
