# Execution-to-review independent engineering handoff

RV-09-01 follow-up: the independently identified temporary-source-copy defect is
addressed by the [protected-evidence correction](rv09-01-verification.md). It removes
filesystem reconstruction rather than relying on process-exit cleanup. The test
results below remain the original integration evidence, not final-head proof of
that later correction.

Date: 2026-10-19. Draft [PR #9](https://github.com/Stevemeg/RepoVox/pull/9), unmerged,
stacked on `925752b8df38668349b9ef5a45a34cac7d948253`. This follow-up preserves
`43410390d9a4cc71c9dd429d10df2da0d5df05df`; it does not rewrite accepted history.
Final head, owner attribution and final-head CI are recorded in the PR description
and consolidated local report. Previous-head CI is not proof of this change.

## Defect and implementation

An execution-stage claim ends when its stage/execution closes. It cannot authorize
later source handoff, response capture, reference sealing, reveal or comparison.
The previous adapter had no concrete independent post-execution authority.

[ADR-0020](../adr/0020-post-execution-custody-authority.md) and the
[normative review contract](../development/custodian-review.md) specify the correction:

- `tools/phase2_custodian_review.py`: authenticated successful SQL closure binding,
  separately pinned owner key, exact signed operation grants, retained original
  evidence validation, sequence/nonce acknowledgments, reveal/scoring and closure.
- `tools/phase2_custodian_adapter.py`: explicit owner/tenant execution binding,
  one-use genuine claim handover and final-output collection before SQL publication.
  Real execution requires concrete claim/watchdog gates; boolean fixture predicates
  require an explicit synthetic override. No arbitrary callback authorizes review.
- `tools/phase2_custodian_lifecycle.py`: additive new-namespace version 1.1 with
  durable operation deadlines and final-seal recovery. Version 1.0 remains readable
  and usable without migrating any old namespace or receipt.
- `tools/phase2_custodian_watchdog.py`: concrete local observation of advancing
  loops and actual process identity; no container-running substitute for health.
- `tests/integration/test_execution_review.py`: actual scoped Python/JS/TS analysis,
  PostgreSQL/S3, real prediction projection, restricted custody, signed synthetic
  review, frozen scoring, closure and cleanup. Transport alone supplies synthetic
  repositories; claims, output storage, projection and scoring are not mocked.

All `apps/api/repovox/analysis`, `evaluation`, `pilot` and migration source remains
unchanged against the accepted control-plane tree. Analyzer/scorer stays
`711184e82128c7b0a6f3978cfc1cf13975db39ef`. Migration 0004 and CP-01/02/03 are
unchanged. No historical Store, v1 identity, reference, score or acceptance rule changes.
The already-locked cryptography 50.0.2 becomes an explicit offline dev-tool dependency;
no resolved package version changes. No new service, HTTP route, Celery task or SQL grant.

## Authority, atomicity and blindness

The authenticated controller must observe immutable EXECUTION_CLOSED, exact closed
generation and manifest. Original source/scope, A, original analysis, projected B
and the first two event commitments are revalidated. Preserve the resulting binding
hash and independently enrolled owner-key fingerprint outside custody.

Every review grant signs exact tenant/owner/namespace/attempt/family/source/B,
operation, input hash, previous head, nonce, approval-evidence hash and UTC lifetime.
It lasts at most 24 hours and never beyond either original custody authorization or
retention. Successful execution can release its lease; review cannot acquire a stage,
renew SQL authority or extend retention. Owner signatures authenticate the enrolled
key holder, not ChatGPT provider identity or human/semantic review.

The namespace lock precedes SQLite transactions. There is no SQL/network callback
under that lock. A durable intent reserves payload, signed approval, nonce receipt,
event and slot before byte creation. Final commit exposes the entire batch; close
also commits SEALED in that transaction. Complete recovery rehashes/fsyncs and checks
the original operation deadline; incomplete/expired intents invalidate. Identical
signed duplicate submissions return the original acknowledgment. Different payloads,
heads, keys, contexts, replay or sequence forks fail. Expiry fences all further writes.

Only A is returned by handoff. B is returned only after event five and source/reference
validation. Initial reference replacement is rejected. Capture preserves exact input
bytes; the synthetic response is introduced only at capture, not seeded as source
evidence. The scorer receives retained original analysis as well as original B.
Post-reveal corrections remain governed by the unchanged diagnostic-only contract.

## Observed tests and environment

Dedicated VMware guest identity `08502791c07d4f18a13346dc4e4d6690`, hostname
`repovox-verify-08502791`, Ubuntu 24.04.5, two vCPUs, 2048 MiB and a separate 30 GiB
virtual disk. Docker Engine 29.9.1 / Compose 5.6.0, daemon
`b1cee4cb-4d00-4aea-bf74-1eec5eecff60`, guest-local Unix socket and `/var/lib/docker`.
No Windows shares, historical custody, Docker Desktop/WSL endpoint or unrelated VM.
Synthetic testing has no guest default route. New service namespace:
`repovox-review-e904b0ba5d78`; fresh PG16.13, Redis7.4.9 and SeaweedFS4.17 resources.

| Actual local command group | Observed result |
| --- | --- |
| Full Linux application/service suite at recorded pre-handover-test tree | 634 passed, 84 skipped, 346 warnings, 151.09s |
| Separate restricted lifecycle/review matrix | 78 passed, no skips, 106.48s; actual Linux files, processes, locks, deadlines and cleanup |
| Genuine execution-to-review suite using shipped collector | 5 passed, 1 warning, 114.04s |
| Genuine claim identity/one-use handover regressions | 2 passed, 5.40s |
| Genuine PostgreSQL and ordinary-worker crash/restart during protocol | 1 passed, 1 warning, 47.01s including fixture setup; original 45s custody lifetime unchanged |
| Legacy actual retention/container-identity/byte-transfer matrix | All 35 scenarios passed |
| Supplemental source pipelines, worker restoration and controller crash | Seven passed; old-0004 fixture initially missing, then that distinct case passed in 2.02s |
| Windows units | 527 passed, 38 skipped, 338 warnings, 19.31s |
| Frontend units | 17 tests / 3 files passed; lint, types, build and audit pass |
| Static/contracts/docs/cost/readiness | Ruff/format, mypy 57 app files, doc tools and versioned contracts pass |
| Dependencies | No known Python vulnerabilities; local unpublished RepoVox unauditable; npm audit zero vulnerabilities |

Skips are not passes. Restricted cases skipped as UID 10001 run separately as actual
UID/GID 10002 with zero capability sets, NoNewPrivs, 0700 directories, 0600 files,
read-only root and bounded tmpfs. UID 10001 enumeration/read fails. Cleanup removes
registered bytes and preserves an unrelated sentinel. Synthetic execution cleanup
also verifies its exact object-storage spool and temporary source copy are empty.
Final-head CI reruns the full suite including the added handover case, all restricted
cases, genuine PG protocol tests, browser regression and secret scan.

The restart rehearsal stops/starts a new ordinary worker and restarts the new PG
container after durable execution closure. Actual process IDs change, stale claims
remain denied and post-execution review continues within its original deadline.
Controller process exits, watchdog crash/recovery, actual disk-full, write-intent
kill points and post-expiry deletion are separately exercised. No original worker,
incident database or real custodian is restored.

The applied CP-03 function body matches accepted SQL; four pilot tables force RLS,
ordinary app/worker identities lack protected pilot authority, public pilot EXECUTE
grants are zero and the final disposable ledger has no executable attempts. The
old-0004 test demonstrates identical old function hashes after `upgrade head`:
`f89e669a581e5e44c99f2f4d1f48e685a73ba585b6690ce4cc2c6b083900e061`.
The corrected function definition hash is
`83d8462906dc5203d6fccfe6a3433b1572669606d9257a4687a423d339f6579f`.
An old installed draft 0004 therefore needs separately approved recreation or a
forward migration; this work migrates no persistent database.

## Adversarial review map

| Requirement | Proof location |
| --- | --- |
| Expired execution vs later review; stale claims; completed execution cannot restart | Genuine PG execution/review suite; accepted CP expiry tests |
| Canceled/invalidated/expired ACTIVE attempt cannot hand off | Failed-attempt bootstrap tests; CP cancellation/reconciliation suite |
| Review/execution authority substitution; boolean predicate rejection; wrong owner key | Restricted review authority substitution and signature tests |
| Wrong tenant, owner, family, attempt, namespace, scope, B or head | Parameterized signed-binding negative controls |
| Forgery, payload modification, approval mismatch, expired grant, replay | Signature and acknowledgment tests |
| Concurrent submission; exact duplicate acknowledgment; crash after commit | Real forked-process event/receipt tests |
| Missing original source; changed sealed reference; premature reveal/comparison | Integrity and ordered-operation tests |
| Authorization expiry during write; capture deadline | Timed intent/recovery test and fail-closed capture test; deadline unchanged |
| Retention expiry during activity, incomplete intent, disk-full, unexpected file, links/path escape | Actual lifecycle/retention matrices |
| Watchdog unavailable, stalled, restarted or process dead | Actual observer/process tests and 35-case runtime matrix |
| Controller crash, SQL restart and worker restoration | Genuine protocol restart plus accepted supplemental crash/recovery proofs |
| SEALED/EXPIRED reopening; withdrawal; atomic seal recovery | Irreversible transition and close crash tests |

Intermediate failed commands remain preserved: missing scorer envelope evidence,
fixture import path, short-lived controller probe startup, intentionally protected
expiry edits, missing historical SQL fixture and timing-sensitive capture location.
The capture test now checks the exact expiry error and both safe outcomes: no bytes/
event/nonce if denied at admission, or invalidation/cleanup after an entered write.
The independent timed-write test still requires rejection/recovery during the write.
No security timeout, role, capability, source limit or error classification is relaxed.
Operational command errors and all stderr are retained separately from test passes.
The first pushed integration run passed 635 application tests (84 skipped), then
failed its separate restricted run: the direct Docker command omitted the Python
module path needed by the watchdog subprocess, and concurrent cleanup exposed a
pre-lock check racing SQLite journal unlink. The follow-up supplies that explicit
module path and validates transient journal metadata only under the namespace lock;
immutable path checks remain before locking. A real malicious journal hard-link
regression requires rejection before SQLite opens it. No link check is suppressed
inside the lock and no protected historical namespace is touched.
An intermediate 76-pass/two-failure run also exposed test observations treating a
live watchdog's nonblocking lock-busy result as failed closure. Those observations
now handle only explicit BUSY within the existing one-second lock cap; final state
assertions, integrity errors and all expiry deadlines remain strict. Busy is never
reported as successful cleanup or retention readiness.
The restart harness initially used the container-start clock instead of namespace
creation, then default Docker shutdown waits exhausted the fixed custody lifetime.
The latter run correctly failed with `retention_deadline`. The passing crash/restart
uses an explicit one-second shutdown grace for these disposable processes, verifies
durable terminal state before worker restoration, and keeps the original namespace,
operation, controller-probe and restart-coordination deadlines unchanged.

## Preservation, live readiness and external gates

All 315 historical and 91 failed-attempt host-file commitments remain unchanged,
as do 246 prior engineering evidence files. Neither real custodian is mounted,
migrated, deleted or reused. Original deadlines remain **2026-11-14 17:43:39 UTC**
and **2026-11-16 16:53:29 UTC**, including owner-managed host copies. No automated
cleanup for either is implied by synthetic success. Physical deletion while powered
off, failed storage, corruption or unexpected inventory needs operator intervention;
local DAC/checksums are not administrator-proof WORM or forensic erasure.

Original E1 metadata reconciles all 43 tree records and ten selected original files,
Git blob hashes, MIT notices and exclusions. No fresh acquisition occurs. The exact
three approved repositories/pins/scopes remain in the [live runbook](../development/phase2-official-evidence.md).
The prepared configuration is nonexecutable: no real attempt, custodian, owner key,
capture/reveal/comparison approval or new real A/B exists.

Before live work the owner must obtain independent acceptance, enroll the actual
key/provisioning receipts, confirm one fresh exact-scope attempt and verify actual
runtime/retention again. After source-only handoff, independent ChatGPT review and
separate explicit owner grants are required for actual capture, seal, reveal and
comparison. Codex cannot author that reference. Old packets are not automatically reused.

Official EVAL-ENTRY stays UNFROZEN: zero verified human-reviewed families, claims,
edges and variants; human appointment and corpus rights/review/freeze evidence remain
external blockers. All original targets remain. Historical 0/84 is unchanged and is
not measured 0% analyzer accuracy. No real scoring, packet reuse, merge, production
deployment, paid service, training or Phase 3 is performed.
