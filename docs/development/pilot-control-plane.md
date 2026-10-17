# Pilot control-plane contract

Version: `pilot-control-1.0`. Proposed for independent review; engineering only.
Requirements: CP-01 durable cancellation; CP-02 mandatory source scope;
CP-03 atomic outbox eligibility; existing
N-01 evidence integrity and tenant/security/resource controls remain in force.

## Authorization and source manifest

`repovox.pilot.contracts.Manifest` contains owner UUID, approval-evidence digest,
fixed accepted analyzer/scorer revision, exact analysis-file inventory hashes and
one to three distinct families. Each family has a canonical repository, full pin
and complete original selected files with byte size, SHA-256 and source/context
role. Paths, duplicate identities, size limits and canonical JSON are validated.
The SHA-256 commits the complete original manifest bytes. There is no prediction,
reference answer, analyzer claim ID or comparison input.

The controller credential is an operator-managed service authorization. An approval
hash records an independently retained owner decision; it is not authentication of
GitHub, ChatGPT or a human reviewer. Source approval and rights evidence still need
the existing external custody process. This contract grants no rights by itself.

The Python controller accepts an already verified pinned `Snapshot`. The admission
transaction rechecks its repository, canonical URL, public flag, commit, family and
owned project against the approved manifest. It computes the stage-1 commitment
from the exact snapshot bytes. The selected scope precedes acquisition; it is not
derived from analyzer output or a later evaluation reference.

## Authentication and default denial

Bootstrap defines only non-login `rv_pilot_controller` and `rv_pilot_executor`
capability groups. No ordinary service inherits them. An owner separately provisions
nonprivileged logins and credentials; no unrestricted admin API is added. Definitions
and grants are in migration 0004 and `infrastructure/local/init-db.sh`.

Controller authority permits registration, scoped admission, status, invalidation
and execution closure for its tenant context. Executor authority permits only bound
claims, scoped input access/receipts and fenced completion. Pools are tenant-bound;
ordinary roles cannot borrow the route by setting a worker label or publishing a
broker message. No new role has RLS bypass, table ownership, direct registry DML,
private-custodian access or evaluation-schema access. Authenticated service credentials
and trusted code/host remain security boundaries, not administrator-proof isolation.

The direct executor exposes `run` and authenticated outbox `deliver`, with exact
attempt/generation/hash/family arguments. There is no pilot Celery task registration.
Normal `repovox.stage` messages for pilot stages are rejected by the database even
while an attempt is ACTIVE. Normal SaaS projects, retry policies and quotas remain.
The historical outside-Git execution controller is not this route and must not be
reused for another pilot; it is preserved only as incident evidence.

## Transaction boundaries

| Operation | Locks and conditional changes | Commit result |
| --- | --- | --- |
| Register | Owner context and controller credential; immutable UUID/manifest | One durable ACTIVE authorization with fixed expiry |
| Admit | Existing global admission advisory lock, owner quota, attempt; validated family/project/snapshot; original admission plus binding in one transaction | No runnable unbound pilot job; same-family replay returns only its original project/job |
| Claim | Owner quota, attempt, then existing job/stage locks; role/owner/state/generation/hash/family/expiry checks | At most one lease and stage fence; no I/O on denial |
| Receipt | Owner quota and attempt; current exact stage fence and manifest check | One immutable scope receipt for that lease |
| Publish outbox notice | Owner quota, attempt, job, stage, then event row; recheck binding, readiness, unpublished/due status and current deadlines | True only for one eligible NULL-to-timestamp transition |
| Publish result | Owner quota/attempt, then existing completion job/stage locks; valid lease and receipt required | Original upstream digest checks and artifact pointer publication remain atomic |
| Invalidate | Owner quota, attempt, attached jobs in UUID order; ACTIVE/generation compare; existing terminalization revokes stage fences | Cohort INVALIDATED and generation incremented; accepted completed records remain unchanged |
| Close | Owner quota/attempt; every approved family bound and stage 9 succeeded | EXECUTION_CLOSED, generation incremented; no evaluation acceptance claim |

Final publication and invalidation share the attempt lock. If publication wins, it
commits before invalidation; if cancellation wins, the stale publication fails.
Heartbeat and read predicates do not acquire a reverse-order attempt lock while
holding the original job lock. Claim/admission/receipt tests exercise actual READ
COMMITTED connections and independent workers, rather than simulating a mutex.

The wrappers delegate ordinary jobs to private original procedure copies. Those
copies have no PUBLIC/application/worker execute grants. Supported old 2.2 completion
continues for ordinary jobs but cannot publish pilot work. Generic fixture/analysis
admission rejects an already bound pilot project. Source withdrawal through ordinary
project deletion first invalidates the pilot cohort, retaining normal deletion policy.

## Scope enforcement

`Executor` checks the complete engine inventory before network work and binds the
approved family to the immutable job snapshot. Stage 2 uses accepted safe archive
handling and all-file security screening; a second original-byte/hash/size/role check
validates selected files before the archive is written. Whole-archive intake for
safety does not authorize semantic analysis of excluded files.

Stage 3 applies the accepted explicit scope restriction. Before writing its output,
the storage adapter requires that all and only approved source/context paths remain
eligible/context, with original hashes and sizes. Subsequent stages independently
validate that persisted filter input. Missing scope, cross-family substitution,
changed files or a missing filter adapter fail closed. The analyzer only receives
the approved eligible list; test/development paths remain excluded metadata.

Each result write checks its lease before/after the storage call and records an
authenticated scope receipt. Final database completion requires that receipt for
the exact fence. A generic runner without the adapter cannot advance its unscoped
filter result. Receipts are trusted-code assertions; they are not a new expected
answer or independent semantic verification.

## Failure, recovery and delivery

A pilot execution failure invalidates the cohort before returning, even when the
normal error is transient. An expired running-stage lease or legacy `retry_wait`
state is invalidated by reconciliation before ordinary retry promotion. Recovery
retains source/outbox/audit records; it does not reopen terminal rows or drain queues.

Ordinary outbox dispatch excludes pilot bindings. Dedicated listing is advisory;
`rv.pilot_published` independently checks the authenticated owner, ACTIVE attempt,
generation, binding and event/stage/job association. It holds quota/attempt/job/stage
locks, requires a ready stage with remaining attempts, a queued/running job, an
undeleted project and a reserved quota record, then locks the event before evaluating
publication time. The conditional update requires `published_at IS NULL`, due time
at or before the current clock and unexpired attempt/job deadlines. It rechecks event
identity after locking. A lock holder that never changes the tuple must not bypass
the time recheck. False denotes no new publication, including already-published
events; previous timestamps remain unchanged. Rejections are audited.

Publication and claim remain separate transactions. A successful mark is not a
lease or a guarantee of execution; the independent claim gate still enforces quotas
and fencing. Concurrent deliveries obtain at most one new mark and cannot bypass
the claim gate. Rejection events record database actor, attempt/generation and stage;
worker-name strings are never authority. Unknown IDs yield no runnable work.

The authorization expires after 45 minutes without renewal. This is a maximum
authorization deadline, not proof of controller liveness. No automatic pilot consumer
exists, so an ordinary restart cannot resume pending pilot work. After a controller
crash, the operator must inspect/invalidate its durable authorization before recovery;
an expired running lease is closed by reconciliation. A fixed deadline cannot stop
an already admitted external request instantaneously.

`Controller.abort_before_restore` invalidates then rereads terminal status before
calling a supplied restoration action. Persistence failure or an ACTIVE result from
a stale invalidation token prevents restoration. A lost commit acknowledgment is
resolved by durable reread, never source re-execution. The library itself starts or
restarts no services. A cancellation row does not prove that a process has exited.

Object upload cannot be atomic with PostgreSQL cancellation. A raced upload can be
an orphan; it cannot become an accepted result pointer after invalidation. Retain
private diagnostics and use established bounded cleanup/retention. No stronger
instantaneous network/filesystem cancellation guarantee is claimed.

## Migration and private-evidence boundary

0004 is additive, applies only to separately approved database scopes, and was
authorized locally only for isolated disposable tests. Existing migration files and
historical jobs/artifacts are unchanged. Empty-ledger rollback restores the original
procedure definitions and removes new control objects; populated-ledger rollback
fails without deleting lineage. Non-login group definitions remain owner-managed.

CP-03 corrects the unmerged 0004 draft in place: no deployed/persistent migration
was authorized, and previous 0004 environments were disposable. Its public function
signature and grants are unchanged. An already-applied draft 0004 database will not
be repaired by `alembic upgrade head`; recreate a disposable database or obtain a
separately reviewed forward migration before any persistent use. No such persistent
operation is performed here. Tests exercise fresh upgrade and empty-ledger rollback
plus re-upgrade, retaining the populated-ledger rollback refusal.

No control-plane test has a real custodian mount or real evaluation source. Source
extraction/scoring, v1/v2 schemas, gold, official thresholds and historical comparison
are outside this change. Private custodian expiry remains 2026-11-14 17:43:39 UTC,
including existing withdrawal and owner-managed host-copy responsibilities. No packet
reuse, source handoff, blind review, reveal or new E2 execution is authorized here.
