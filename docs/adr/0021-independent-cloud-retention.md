# ADR-0021: External cloud fencing and verified retention cleanup

Status: Design-stage engineering accepted at
`95aa6d265038f0b111eec91770690ebd2016a363`; CR-01..04 corrections proposed for
independent re-review. Date: 2026-10-20. No deployment or pilot approval.

## Problem

The owner cannot provide an always-on laptop/VM or overnight incident response.
The accepted custodian refuses unsafe writes but cannot delete unavailable disks.
Desktop notifications cannot meet this operational requirement.

## Decision

Prepare, without deployment, a dedicated AWS workload account and a separate
retention/security account. Keep restricted Ubuntu custody, accepted analyzer/scorer,
CP-01/02/03 and migration 0004 unchanged. Register every protected destination before
bytes. An external transactional fence supplements existing SQL/local gates.

Use one-time expiry, independently recurring reconciliation, missing-progress alarms,
bounded resumable cleanup and separate read-only absence verification. Restrict
destructive authority to exact approved resources, never mutable tags. Immutable
registry versions and resource intents live outside the guest. Cleanup requires no
guest, PostgreSQL, laptop or owner private key. Real review retains signed grants.

Prefer disposable encrypted EBS storage; register root, database/object-store and
acquisition disks too. Initially prohibit snapshots, backups, replicas and external
exports. Optional versioned objects/uploads/snapshots require explicit registration.
Object Lock is for opaque audit metadata, not protected bytes needing withdrawal.

The implementation is a nondeployable synthetic protocol model, not an AWS adapter,
Lambda handler, IAM deployment or replacement Store. SQLite/mock concurrency does
not establish real provider behavior. See the [design/failure matrix](../operations/cloud-retention-design.md),
[cost inputs](../operations/cloud-retention-costs.json) and
[verification/handoff](../delivery/cloud-retention-design-verification.md).

The [1.1 correction contract](../operations/cloud-retention-review-contract.md)
defines native compound identities, an independently authenticated read-only
verifier/signing interface and durable one-use dynamic-ID creation intents.
Older mock ledgers are rejected without migration. The
[reviewer-copy owner decision](../operations/cloud-reviewer-copy-decision.json)
remains explicitly pending; uncontrolled third-party exports cannot qualify.
No actual provider adapter, credential or real approval is supplied by fixtures.

## Consequences and acceptance boundary

Normal monitoring, fencing and conditional cleanup no longer need the owner online.
Regional/API outages, billing suspension, IAM regressions and unmanaged recipients
can still delay cleanup. Report OVERDUE/INCOMPLETE, never fabricated deletion.
An independently contracted 24/7 incident service is a live prerequisite for failures
automation cannot resolve. No such responder or price quote exists yet.

Independent review, account/region and residency approval, budget, real disposable
API/IAM tests and exact cleanup/escalation receipts precede deployment. A real pilot
needs separate authorization. Historical custody/deadlines and host-copy obligations
are untouched. No official corpus acceptance, production migration or Phase 3.
