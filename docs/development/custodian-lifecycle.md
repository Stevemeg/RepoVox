# Growing evaluation custodian contract

Version: `custodian-lifecycle-1.0`. Proposed for independent review, not production
deployment approval. This is an offline evidence service library and watchdog;
there is no HTTP route, Celery task, customer mount or real-pilot auto-start.

## Provisioning and authorization

Use a new explicitly authorized namespace outside Git. A trusted initializer sets
umask 077, creates its empty parent, applies 0700 before transferring ownership to
10002:10002, and verifies metadata. Enumerate only as actual UID/GID 10002:10002.
The library rejects other identities, supplementary groups, capabilities and missing
NoNewPrivs. Every private file is 0600. The parent, namespace, control and data paths
must be absolute with no symlink ancestry. Capture device/inode pins, immutable plan
hash and schema hash in a separate owner-retained receipt. Never discover identity
from image-inherited labels or an untrusted on-volume manifest alone.

The plan includes version, namespace, tenant, attempt, approved manifest commitment,
creation time, immutable UTC expiry, fixed authorization expiry and authorization
secret commitment. Creation rejects an expired authorization, future creation,
retention above 30 days, wrong metadata or existing namespace. No code can extend
the plan. A shorter owner-approved limit wins. Restart, read, write, closure, retry
and receipt export never refresh either expiry. Real secret generation and permanent
credential provisioning are not performed by synthetic tests.

A still binding-valid owner token may revoke/withdraw after its read/write authority
expires. That cleanup-only operation cannot read, write, reactivate, seal or renew
authority; it only increases the fence and admits deletion. The watchdog itself has
no write credential and needs no expired execution authorization to enforce expiry.

Before activation obtain two advancing watchdog loops, bound to the committed plan,
UTC deadline, exact source, actual process birth/command, UID/GID/groups, zero
capabilities and NoNewPrivs. Missing, stopped, changed, stale over three seconds,
expired or repeated progress is unavailable. `validate_progress` checks these
observations; the trusted observer must independently obtain the actual /proc and
Docker identity, not copy process assertions from a heartbeat. Activation requires
the resulting fresh bound receipt. A receipt is local trusted-operator evidence,
not authenticated provider identity or a defense against a compromised custodian.

Provision the watchdog with an approved immutable image, read-only root, no added
capabilities, network none, no restart-based expiry refresh, only its exact custody,
read-only config and private status mounts. Check image ID, created container ID,
command, environment, purpose/namespace/nonce, actual volume creation/mount identities,
permissions and plan/config byte hashes against a prior provisioning plan and saved
creation receipt. Reject every mismatch; familiar labels never select a role.
Keep ordinary Compose working-directory checks. No application/API/routine worker
container can receive this mount or token. The watchdog holds no PG or broker secret.

`CustodianStore` requires independent admission and retention readiness gates before
and after each operation. A test predicate returning True is permitted only in
synthetic fixtures. For active pilot execution `PilotLeaseAdmission` obtains its
actual stage fence through the unchanged authenticated `Executor.claim`, binding
owner, attempt, generation, manifest, family and stage. Each later check calls the
accepted lease/scope SQL. Wrong attempt, changed manifest, cancellation, stale fence
or expiry fails. It must not claim again through the ordinary runner. The trusted
offline controller owns stage scheduling and the returned lease; no new route or
SQL grant is introduced. [Offline review grants](custodian-review.md) provide the
separate post-execution path; a closed execution lease cannot authorize review.
New review namespaces use additive version 1.1 and durable per-batch operation
deadlines. Historical 1.0 namespaces retain their original receipt/schema unchanged.

## Durable states and irreversible transitions

| State | Meaning and allowed next state |
| --- | --- |
| CREATED | Plan, ledger and receipt durable; protected writes forbidden; activate to ACTIVE after health proof |
| ACTIVE | Authorized evidence growth; may close SEALED, invalidate INVALIDATED, withdraw WITHDRAWN, or expire EXPIRING |
| SEALED | Growth permanently closed; authorized integrity-checked reads until expiry; may invalidate/withdraw or expire |
| INVALIDATED | Authorization generation increased; no reads/writes; tick enters EXPIRING immediately |
| WITHDRAWN | Explicit owner withdrawal revokes generation; tick enters EXPIRING immediately |
| EXPIRING | Durable cleanup fence; no read/write/reopen; only resumable cleanup to EXPIRED |
| EXPIRED | Irreversible; data inventory empty and deleted statuses committed; repeated cleanup observes the same terminal result |

Execution closure in PostgreSQL is distinct from custody closure. Do not seal custody
after the pre-review source handoff if separately authorized later evidence must be
collected. Keep its original deadline; a review extending beyond it loses eligibility
and requires a separately authorized new attempt, never extension or reopening.
SQLite triggers protect immutable plan and terminal transitions; the receipt pins
the schema. Audit commitments form a verified hash chain. The trusted UID/host can
still alter disk intentionally; these are detection and cooperative concurrency
controls, not administrator-proof storage.

## Transactions, locks and crash recovery

Lock ordering is watchdog singleton flock (watchdog only), namespace flock, then
SQLite transaction. Writers acquire only the last two; no code takes them in reverse,
waits for another namespace, or holds a PG/network lock while taking them. Watchdog
lock acquisition is nonblocking. A single writer/read/transition admission may wait
up to one second for the namespace lock; it then checks the original deadline and
authorization before any work. This bounded acquisition is not a pilot retry and
does not extend a lease, heartbeat freshness or expiry. Busy beyond that bound is
an explicit failure, never successful write or health progress.
The watchdog retries only its retention check; it cannot retry a pilot operation.

1. Check fixed identity, receipt, mode, inode, SQLite quick_check/schema/plan/audit,
   real time, authorization and state. A deadline observation commits EXPIRING and
   increases generation before any further write admission.
2. Recover any previous write intent. Validate all known files and reject unexpected
   files/directories/links. A complete batch is rehashed, fsynced, and marked COMMITTED
   in a durable transaction. Missing/partial batch invalidates the whole namespace;
   it never becomes a complete reference, event or prediction.
3. Reserve all names, hashes, lengths and event reservation, if any, as INTENT using
   BEGIN IMMEDIATE and synchronous EXTRA COMMIT. No evidence byte precedes intent.
4. Write flat validated names with O_EXCL/O_NOFOLLOW and mode 0600 through the pinned
   data-directory descriptor. Fsync each file and directory, verify exact readback.
5. Recheck time, token and state. Commit all file statuses together, including the
   batch's event eligibility. Only then acknowledge; the adapter rechecks its external
   gates before returning. Cancellation racing an external gate may leave a retained
   orphan; it cannot authorize successful upstream result publication, which remains
   independently fenced by CP-01/02/03. This is not a distributed atomic transaction.

EXTRA is read back as 3 on every connection. In DELETE journal mode it also syncs
the journal directory after commit unlink; FULL alone is not a sufficient power-loss
durability claim. This follows [SQLite's synchronous contract](https://www.sqlite.org/pragma.html#pragma_synchronous)
and [atomic-commit assumptions](https://www.sqlite.org/atomiccommit.html). Actual
process-crash tests are not physical power-cut certification of a disk/controller.
The filesystem and hardware must honor fsync; uncertain storage never qualifies.

Exact duplicate committed bytes under all the same names are idempotent; mixed old/
new names, changed bytes, changed reservation or a new body for an occupied name are
rejected. Acknowledgment loss does not rerun analysis: recover and read the original
committed bytes/reservations. New timestamped event creation is a different submission
and must not overwrite a lost original event. Bounds are 5000 files, 50 MB total,
50 MB per file and eight files per atomic batch. Operators must also bound storage
for SQLite metadata, command logs, temporary acquisition and external host copies.
The ledger is capped at 16 MB and 15000 audit entries; repeated closure is idempotent.
Those bounds exceed the legitimate maximum for 5000 evidence files, but do not
permit an unbounded stream of metadata. Limit failures block admission and require
operator review rather than retaining unregistered bytes.

## Expiry and operational failure

The namespace lock serializes deletion with writers. If expiry occurs during a
write, the writer's final authorization check commits the expiry fence and refuses
acknowledgment. Its known INTENT remains eligible for cleanup. The watchdog cannot
delete under a live writer; stale health blocks further operations and requires
operator intervention if the bounded writer does not exit. Crashes release locks.
After host/process restart, the original deadline and durable intent are reread.

Before unlinking, validate the complete inventory, same device, regular files,
owner, mode, single link, lengths and committed hashes. Only ledger-registered names
are unlinked through the pinned directory FD. INTENT may contain partial approved
bytes, but is never readable as completed evidence. Every unlink is directory-fsynced.
A crash after an unlink and before ledger completion resumes missing registered
names only after durable EXPIRING. Complete the transaction to EXPIRED only when no
protected data entries remain. An unrelated sentinel must be untouched. Retain only
minimal opaque bindings, hashes, lengths, states and cleanup/audit commitments in
control; no source, response, prediction, reference or arbitrary descriptive text
enters SQLite. Host copies and temporary stores have separate enumerated cleanup.

Unexpected entries, replaced directories/lock/ledger, corruption, symlinks, hard
links, metadata errors, read-only/full disk, fsync/unlink failures or uncertain
inventory fail closed and emit errors. They do not authorize recursive deletion or
claim completed expiry. Disk-unavailable/host-off physical deletion cannot be timely;
after recovery cleanup must run before any admission. An alert/manual response is
required at the original deadline, including safe containment, positive inventory
identification and owner-authorized cleanup. No automatic deletion of unknown data,
retention extension or claim of forensic secure erasure is made. External acquired
source and analysis/object-storage copies need their own bounded retention inventory;
the namespace cannot erase data never admitted to its storage boundary.

## Store and chronology compatibility

Use only the explicit new adapter for managed storage. Historical Store and v2
schema bytes are unchanged; no implicit migration or raw append fallback exists.
Content remains tenant-prefixed SHA-256 naming. Original response bytes are screened
under the accepted policy but never reencoded or reconstructed. Event body and
sequence slot share an intent batch; event ordering/context validation is reused.
The new prereveal/reveal/comparison wrappers reuse accepted semantic/source validators
and scoring, with new storage writes. They return new event bytes to the controller
so it can retain the actual chain. They are not invoked for real evidence here.

Required actual chronology remains SOURCE_APPROVED, PREDICTION_SEALED,
SOURCE_HANDED_OFF, RESPONSE_CAPTURED, REFERENCE_SEALED, PREDICTION_REVEALED,
COMPARISON_SEALED. No future event is fabricated. B must be sealed before A handoff;
reference and capture commitments must validate before reveal. Reviewer receives
source-only exports, never a custody mount, secret or privileged adapter. Codex does
not author real gold. Local time/hash evidence does not authenticate ChatGPT identity.

See [verification and reproduction](../delivery/custodian-lifecycle-verification.md),
[blind protocol](evaluation-v2-blind-protocol.md),
[official evidence requirements](phase2-official-evidence.md) and
[ADR-0019](../adr/0019-growing-evaluation-custodian.md).
