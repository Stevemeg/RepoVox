# ADR-0017: Pilot control-plane fencing and source scope

Status: proposed for independent engineering review. Date: 2026-10-16.

## Context

CP-01: a manual exploratory acquisition timed out. The controller exited but restored
ordinary services while its durable job remained retryable. Database reconciliation
and the original outbox notification permitted an ordinary worker to claim another
attempt. This was not revival of an already-cancelled job. The initial manual call
had no broker acknowledgment. Historical ACK/message IDs and the exact transport
timeout subphase were not retained and remain unknown.

CP-02: ordinary execution lacked the approved scope adapter and admitted excluded
test files. Stopping a worker, checking queue emptiness or changing a worker-name
string cannot enforce execution authority or scope.

The accepted analyzer/scorer revision is
`711184e82128c7b0a6f3978cfc1cf13975db39ef`. The owner authorized only a control-plane
engineering correction, disposable tests and draft independent review. No real pilot
execution, custody change, packet reuse, reveal, gold or scoring is authorized.

## Decision

Migration 0004 adds immutable attempt/binding/validation/audit metadata and wraps
existing control-plane procedures. Their original implementations remain private
delegates; ordinary unbound jobs retain their behavior. Extraction, canonical
identities, verifier/scorer mathematics and evaluation contracts remain unchanged.

Attempts bind exact approved manifest bytes and SHA-256, tenant, family identities,
pins, original-file hashes/roles, engineering versions and an authorization expiry.
The state machine is `ACTIVE -> INVALIDATED | EXECUTION_CLOSED`. Terminal state and
original commitments cannot be rewritten. Generation increases on terminalization;
stage fences and leases are revoked through existing job termination primitives.
`EXECUTION_CLOSED` describes execution only, not independent evaluation acceptance.

Admission commits job, snapshot, stages, quota reservation, outbox event and immutable
pilot binding together. Ordinary admission cannot add jobs under a bound project.
Claims require the exact tenant, attempt, generation, manifest hash and family under
database locks. First pilot failure invalidates the cohort atomically, including
transient network failure. Recovery closes expired leases/retry states instead of
authorizing another execution. Final publication requires a valid lease and a
scope-validation receipt for that precise stage fence.

Pilot execution uses a narrow authenticated **direct** route, not a new Celery task
or administrative HTTP API. Ordinary claims and dispatch exclude bound pilot work.
Two non-login capability groups distinguish controller and executor authority;
login provisioning remains an explicit operator decision. No runtime receives
superuser, BYPASSRLS, CREATE privileges, custody mounts or evaluation-schema access.
Broker messages, worker labels and supplied hashes are not authentication.

The trusted adapter checks the canonical manifest and exact engine inventory before
network work, validates original selected files, narrows the filter manifest, and
rejects unapproved eligible/context paths on subsequent reads and writes. A missing
adapter cannot publish a filter result or progress into broader semantic parsing.
The database validation receipt is a trusted executor assertion, not hardware
attestation or independent semantic review; a compromised privileged operator is
outside this security claim.

## Atomicity and limits

The supported isolation level is PostgreSQL READ COMMITTED. Owner-quota and attempt
locks serialize pilot claims, receipts, publication and cancellation; existing job
and stage locks protect lease ownership. Admission retains global quota ordering.
Cancellation commit is the fencing boundary. Existing heartbeat/scope checks can
observe already-admitted work before that commit; subsequent accepted publication
must pass the new gate. A network call or object upload already in flight cannot be
retracted instantly. A raced upload can be an orphan, never an accepted pointer.

The direct route has no background pilot consumer to resume after routine service
restart. Authorization has a fixed 45-minute maximum, matching the existing job
limit; it is not a short renewable controller heartbeat lease. Claimed-stage lease
expiration and legacy retry state cause recovery invalidation. Pending work after
an abrupt controller death remains fenced from ordinary workers, and a recovered
controller must invalidate/inspect before restoring or explicitly continuing any
operation. No immediate physical quiescence guarantee is inferred from a DB row.

The controller's abort-before-restoration interface verifies durable terminal
status. Database uncertainty or an unconfirmed stale generation prevents the
restoration callback. No automatic execution retry follows a failed control call.

## Compatibility and rollback

All pre-existing migrations and historical rows remain unchanged. Ordinary readers
accept 0003 or 0004; pilot execution requires 0004. Empty-ledger downgrade restores
the original procedure definitions and removes only new control-plane objects.
A populated ledger blocks downgrade rather than deleting lineage. Temporary schema
CREATE authority belongs only to the existing non-login migration executor and is
revoked at completion. The role definitions themselves create no login/service.

Private evidence remains outside Git and CI. Synthetic tests use new isolated
PostgreSQL/Redis/S3 resources and no evaluation repositories or reference answers.
The historical 0/84, official human-review counts and UNFROZEN status do not change.
Any use of retained packets or a real execution requires a separate owner decision
after independent review of this correction.

See [control-plane contract](../development/pilot-control-plane.md),
[verification](../delivery/phase2ce-control-plane-verification.md) and
[reviewer handoff](../delivery/phase2ce-control-plane-reviewer-handoff.md).
