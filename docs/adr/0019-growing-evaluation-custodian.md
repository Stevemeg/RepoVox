# ADR-0019: Durable growing evaluation custody

Status: proposed for independent security and engineering review. Date: 2026-10-18.

## Context

The accepted v2 Store provides private, exclusive byte writes and custody chronology.
It has no active retention inventory. The fixed-inventory rehearsal in ADR-0018
cannot safely admit new evidence. Removing its synthetic guard would leave write,
crash and deletion races unresolved. The owner authorized an additive offline
lifecycle and isolated synthetic verification, stopping before real acquisition.

## Decision

Add `custodian-lifecycle-1.0` under trusted operational tooling. Keep historical
Store, analysis, scoring, canonical identities, SQL 0004 and historical custody
unchanged. Use one new namespace per attempt, a committed immutable plan, externally
retained provisioning receipt, restricted custodian identity, SQLite durable ledger
and exclusive filesystem bytes. No new dependency or application DB migration.

An entire namespace operation takes a bounded namespace flock before SQLite
BEGIN IMMEDIATE. A watchdog additionally takes a lifetime singleton lock first;
writers never acquire that singleton lock. No network/PG callback or second
namespace lock is acquired inside the protocol. Durable intent precedes file
creation; file and directory fsync precede completion. Recovery either verifies and
fsyncs the complete batch or invalidates the namespace. Expiry commits its fence
before deletion and resumes known deletions after a crash. See the normative
[lifecycle and failure protocol](../development/custodian-lifecycle.md).

The new explicit adapter preserves original bytes and accepted event validation,
and registers event content and its reservation in one batch. Historical append
functions must not write directly into a managed namespace. Future reveal/comparison
wrappers reuse accepted validators and scorer; they require separate owner approval
and the original source-only chronology. No real review or scoring runs here.

## Consequences

Only local POSIX filesystems with working flock, SQLite DELETE journals, fsync and
directory fsync are supported. Network filesystems, external writes, shared custody
mounts, privileged runtime bypasses and in-place historical migrations are excluded.
UID/GID 10002:10002, 0700 directories and 0600 private files remain mandatory.
The operator, host and sole custodian identity remain trusted; no administrator-
proof WORM, forensic media erasure or distributed PG/filesystem atomicity is claimed.

Physical expiry cannot be guaranteed while a host is off, storage is unavailable,
an in-flight writer is stalled or integrity is uncertain. Admission still fails
closed. Fresh heartbeat, missed-expiry recovery, operator escalation and independent
owner-managed cleanup obligations are required. No readiness claim survives absent
or stale health. Existing deadlines are unchanged and no existing custodian mounts.

See [retention runtime](0018-isolated-retention-runtime.md),
[control-plane safety](0017-pilot-control-plane-safety.md),
[review handoff](../delivery/custodian-lifecycle-verification.md) and
[official preparation](../development/phase2-official-evidence.md).
