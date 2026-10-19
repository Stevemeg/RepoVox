# Offline execution-to-review custody contract

Versions: `custody-review-binding-1.0`, `custody-review-authorization-1.0`,
`custodian-lifecycle-1.1`. Proposed for independent engineering/security review.
This document adds an operational interface; accepted evaluation schemas, scoring,
canonical identities, CP-01/02/03 and PostgreSQL migration 0004 do not change.

## Authorities and lifetimes

| Authority | Required evidence | Permitted work | End |
| --- | --- | --- | --- |
| Execution | Actual authenticated SQL claim, owner, explicit tenant, attempt/generation, manifest, family, stage/fence and current scope SQL | Approved scoped static-analysis stage and guarded evidence collection | Stage lease/SQL authorization expiry, cancellation or execution closure |
| Review | Successful immutable SQL closure receipt; pinned owner public key; signed operation/payload/head authorization and original approval bytes | Exactly one named evidence operation | Signed deadline, at most 24 hours; no later than original custody authorization or retention |
| Local custody | Original namespace secret commitment and generation, restricted UID and pinned filesystem receipt | Durable storage primitives, never an independent owner approval | Original fixed custody authorization, withdrawal, invalidation or expiry |
| Retention | Pinned namespace and inventory; actual restricted watchdog process | Observe, fence and remove registered bytes | Irreversible EXPIRED; no evidence reads/writes |

Never extend a plan to accommodate review. A new grant can authorize a later
operation only within the original lifetime. It does not revive execution or renew
custody. SEALED prevents all growth. Withdrawal/invalidation increments the local
generation and prevents reads/writes; cleanup does not need an unexpired write grant.

`LeaseBoundExecutor` passes the admission gate's actual authenticated claim exactly
once into the unchanged `Executor.run`. It shares the gate's one-use lock across
views, checks exact stage/attempt/generation/manifest/family and current SQL scope,
and retains every original runner heartbeat, scope, storage and publication fence.
It neither claims twice nor renews a lease. This is the shipped handover adapter;
the integration test does not replace PostgreSQL claim behavior with a mock.
`ExecutionEvidenceStorage` seals the original verify envelope and accepted real
projection through the concrete custodian gate before the runner's successful SQL
publication. It delegates actual object I/O and never authors reference answers.
The integration uses this shipped collector, rather than replacing storage writes.

## Closure and owner enrollment

`ReviewSession.establish` requires a real least-privilege PostgreSQL `Controller`.
It reads `EXECUTION_CLOSED`, generation + 1 and exact manifest commitment through
the accepted authenticated status procedure. It independently verifies frozen
engine file hashes, family membership, owner/tenant/repository/pin/file scope,
original source and proof bytes, original analysis, accepted verdict projection,
source-only packet and retained event slots. No prediction is made into a reference.
An initial blind chain must contain SOURCE_APPROVED and PREDICTION_SEALED only.

The returned closure binding includes these commitments, closed generation,
observation time, namespace plan hash and owner public-key fingerprint. Preserve
its SHA-256 outside custody with the provisioning receipt. Reopen only against
that expected hash and exact public key; do not reconstruct a replacement binding
after a crash. PostgreSQL terminal immutability makes later offline verification
possible without keeping a stage lease or database credential in the review tool.

The owner independently provisions an Ed25519 key and approves its fingerprint.
Keep its private key out of custodian, API/worker containers, Git and logs. The
offline verifier accepts raw public-key bytes, not a key named by a submitted grant.
This implementation never creates a real owner key, signature or approval evidence.
Its synthetic fixture signer cannot be used as real approval.

## Signed authorization record

The JSON envelope has exactly `grant` and base64 `signature`. The signature covers
`canonical(grant)`: sorted keys, compact separators, UTF-8, no nonfinite numbers or
duplicate keys. Grant fields are exact; unknown fields fail closed:

| Field | Binding |
| --- | --- |
| version | `custody-review-authorization-1.0` |
| binding_sha256 | Independently retained closure receipt commitment |
| namespace, tenant, owner, attempt, family | Exact enrolled closure identity |
| scope_sha256, prediction_sha256 | Exact approved source and original sealed B |
| operation | One operation from the table below; never execution |
| input_sha256 | Exact submitted payload bytes |
| previous_head | Exact preceding custody event commitment |
| issued_at, expires_at | UTC; issued after closure observation, current, at most 24 hours and within both original custody deadlines |
| nonce | 32 lowercase hex characters, single namespace-wide use |
| approval_evidence_sha256 | Exact original owner approval bytes retained with the operation |

The envelope is bounded to 16 KiB and approval evidence to 1 MB. A cryptographic
record proves possession of the separately pinned owner key. It does not prove
provider identity or the truth of either the reference or approval prose. Real
capture, reveal and comparison each require a new explicit owner instruction and
signed grant; a broad earlier pilot approval is insufficient.

| Operation | Required previous events | Input/output |
| --- | --- | --- |
| handoff | 1–2 | Exact source-only A; returns only A, records SOURCE_HANDED_OFF |
| capture | 1–3 | Original reviewer response bytes unchanged; records RESPONSE_CAPTURED |
| seal_reference | 1–4 | Source-validated initial reference, revision 1; exact A/B/response and source-only attestation bindings; records REFERENCE_SEALED |
| reveal | 1–5 | Exact original B; revalidates source/reference, records PREDICTION_REVEALED before acknowledging disclosure |
| compare | 1–6 | Exact sealed reference; original B and original analysis supplied to unchanged scorer; records COMPARISON_SEALED |
| close | 1–7 | Exact final event body; commits receipt and SEALED in one transaction |

No generic read/export interface is handed to the independent reviewer. The
privileged custodian necessarily can read B; the reviewer receives only the handoff
output, source schema and instructions. No key, database credentials or custody
mount goes to a reviewer, routine API or worker. Initial reference replacement and
wrong response/source bindings fail. Later post-reveal corrections use the separate
accepted diagnostic-only revision protocol, not a reopened initial session.

## Atomicity, replay and recovery

Signature and live watchdog progress checks occur outside namespace locks. No
network/SQL request runs while a namespace flock or SQLite transaction is held.
The lock order remains watchdog singleton (watchdog only), namespace flock, then
SQLite BEGIN IMMEDIATE. There are no cross-namespace locks or reverse acquisitions.

`Lifecycle.put` atomically reserves one batch containing new protected payload,
signed grant, approval evidence, nonce acknowledgment, event body and event slot
(maximum six files here). Already committed content is read/verified, never
overwritten. The durable 1.1 batches row records the operation deadline and whether
the batch closes custody **before** writing any protected bytes. Original bytes,
exclusive creation, fsync/readback, deadline/fence check and final COMMITTED/event
visibility retain the accepted lifecycle rules. Closing commits SEALED in that
same final transaction. Concurrent event submissions cannot fork a sequence.

Identical signed requests return the original acknowledgment/output without a new
event. Changed payload, grant, nonce reuse or head fails. A concurrent loser may
receive a conflict and later retrieve only the identical committed acknowledgment;
this is not permission to rerun an analyzer or a failed real attempt.

On crash, complete intents are rehashed and fsynced. A timed batch can commit only
before its original deadline; missing/partial/expired intent invalidates custody
instead. Expiry can erase these registered bytes even when an operation failed to
acknowledge. Recovery never reissues grants or extends deadlines. Unexpected files,
changed schema/inodes, links, wrong owner/mode, corruption or disk-full remain
fail-closed with operator escalation. Final checks cannot make filesystem writes
and wall-clock deadlines a distributed real-time transaction; loss of health or
authority prevents successful acknowledgment, and the inventory bounds cleanup.

`LiveWatchdog` observes two advancing loops plus actual /proc UID/GID/groups,
capabilities, NoNewPrivs, command, process birth and source checksum. Missing/stale/
stalled/dead evidence blocks review. Restart requires rechecking the new process
binding, never a new plan or expiry. Host shutdown cannot guarantee on-time deletion;
operator cleanup after recovery includes tmpfs, synthetic object storage and any
separately recorded host copies. No administrator-proof WORM or forensic erasure
claim is made.

## Live execution boundary

The [official evidence runbook](phase2-official-evidence.md) remains required. First
obtain independent acceptance of this change, owner confirmation of one fresh exact
three-repository attempt, actual key enrollment and operational retention receipts.
No real capture/reveal/comparison grant has been issued by this engineering work.
Use real source-only independent review and stop at handoff. Historical custody,
both November deadlines, 0/84 and official UNFROZEN/zero human-reviewed counts remain
unchanged. Synthetic protocol comparisons are not benchmark accuracy or gold.
