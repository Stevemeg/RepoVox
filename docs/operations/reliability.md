# Reliability and operating procedures

Proposed, 2026-10-08. Targets in [PRD](../product/prd.md#nonfunctional-requirements-and-success-metrics); transitions/retries solely defined in [data model](../architecture/data-model.md). [Deployment/rollback](deployment.md) · [Costs](cost-model.md)

## Observability and alerting

Structured JSON logs: timestamp/severity/service/environment/release/trace ID/job ID/stage/attempt/fence/error code/duration; pseudonymous owner ID only where needed. Do not log raw URLs with tokens, source, prompts, provider responses, secrets or signed media links. OpenTelemetry trace context flows API→outbox→attempt→provider/render; correlate provider request IDs without payload. Sampling must retain errors/security events, avoid high-cardinality job IDs as metric labels.

Metrics: admission/rejection by code, supported success %, queue age/length, stage p50/p95/p99, lease expiration/duplicates, reconciliation backlog, unknown provider operations, tokens/characters/cost vs reservation, render CPU/memory/scratch, MP4 validation failures, DB/Redis latency/errors, URL mint/playback errors, deletion overdue count and backup freshness.

| Alert | Threshold / response |
| --- | --- |
| API unhealthy/error surge | >5% 5xx for 5 min or no healthy replica; owner pager/email, inspect release/dependency, rollback if release-related. |
| Queue/timeout | Oldest admitted stage >5 min or supported-job p95 >20 min; throttle admission, inspect resources/leases/provider status, do not exceed concurrency cap automatically. |
| Worker/quality failures | >10% supported failures over 30 jobs or any ungrounded severe claim in audit; suspend affected stage/template, preserve sanitized evidence, remediate before resume. |
| Cost/abuse | Forecast monthly budget ≥80% warning; ≥100% block new paid admissions. Any job attempts over reserved maximum blocks send; unknown paid outcomes alert immediately. |
| Security | Any cross-tenant signal, secret egress canary or sandbox/network escape: stop admission/paid sends/signing, revoke keys if affected, incident response. |
| Cleanup/backup | Any live deletion >24h or no valid backup/restore coverage for RPO >1h; owner alert, retry idempotent cleanup/backup repair, do not declare restore capability without drill. |

Solo owner owns on-call; no implied 24/7 staffed team. 99.5% API objective and 4h restore target need coverage/budget assessment. Alert channels/escalation contact finalized before production, test notification delivery without sharing customer data.

## Incident handling

Severity 1: source/credential/tenant exposure or uncontrolled billing; severity 2: generation outage, object loss or failed restore; severity 3: degraded latency/local quality defect. Record detection/time/release/scope. Stop affected capability with independent admission, paid-send and URL-signing kill switches. Preserve redacted diagnostics and ledger; avoid copying secrets into tickets. Assess impact, rotate secrets/revoke sessions where relevant, rollback per deployment, notify affected users/owner as legally appropriate, verify recovery and document root cause/actions. Security notification obligations/contacts reviewed before launch. No messages or incident systems configured in Phase 0.

## Recovery acceptance tests

Future implementation tests, not executed results. Each needs DB state/assertions and provider mock call counts; genuine paid evaluation only after authorization.

| Failure injection | Required observation |
| --- | --- |
| Duplicate/out-of-order queue deliveries | One active lease/output per stage, no next-stage execution before predecessor, no double quota/cost settlement; invalid owner messages rejected. |
| Worker death before paid send | Expired lease recovered, unique unsent intent reclaimed safely; at most one valid sender under DB guard. |
| Worker death after provider send before durable response | Unknown operation blocks paid resubmit; recovered response/confirmed no-charge permits progression within deadline, else fails safely. No exactly-once billing claim. |
| Worker death after artifact upload / DB commit | Pre-commit orphan removed; committed result reused without new provider call. Stale worker publish/heartbeat fenced out. |
| Cancel races completion | Job row locking yields one terminal outcome; cancellation-first forbids publication/new calls; success-first rejects late cancellation. Task termination ≤60s. |
| Redis full loss or outage | Durable due stages republished/reconstructed; no job/history/quota loss, duplicate processing harmless. |
| DB outage/deadlock | No new paid sends without reservation/valid lease; transaction retries bounded; reconciliation restores correct stages, unknown charges retained. |
| S3 missing/corrupt/partial upload | Hash/probe mismatch blocks success, retries bounded; eventual cleanup does not delete active committed artifacts. |
| Provider 429/5xx/auth/timeout | Retry only known-safe transient failures, Retry-After honored within deadline; auth/policy fail permanently, no fallback escalation. |
| Deadline/oversized repo/render hang | Absolute deadline includes queue time; resource caps terminate without corrupting other jobs, stable user-facing code. |
| Restore drill | Fresh isolated DB from PITR within RPO/RTO, deletion ledger applied, objects checked, Redis rebuilt, unknown usage reconciled before paid resume. |
| Deployment rollback | Old image handles expanded schema/contracts, admission drains, in-flight old templates preserved; rollback checks status/playback and owner policy. |

Reliability reports must show denominators/exclusions and actual command/test evidence. Every successful video probes codecs/duration/dimensions/size and citations. Periodic human audits catch semantic errors that JSON/schema tests cannot. [Roadmap](../delivery/roadmap.md) makes these launch gates explicit.
