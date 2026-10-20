# RV-09-01 protected-source cleanup correction

Independent-review baseline: `a23303ee0b83301b7db7205956e30d818ab63089` in draft
[PR #9](https://github.com/Stevemeg/RepoVox/pull/9). This follow-up remains on the same
branch and does not rewrite history. Exact final head, CI and private evidence
commitments are recorded in the PR description and consolidated correction report.

## Root cause and correction

`ReviewSession.perform` created `TemporaryDirectory(prefix="rv-review-")` for every
operation. Its finally-based cleanup could not run after SIGKILL. The source tree
was outside the lifecycle inventory, so the watchdog could not discover or safely
delete it. Closure integration also prepared a separate source-validation tree.

The correction eliminates both reconstructions. [CustodySource](../../tools/phase2_custodian_source.py)
maps approved original logical paths to already registered content-addressed source
files. It exposes only the small read interface needed by the unchanged v2 validators:
actual filesystem containment/stat and exact original bytes through `Lifecycle.read`.
The latter checks tenant/namespace/token, current state/expiry, inode, UID/GID, modes,
links and committed hashes. No stat is fabricated and no source validation is skipped.
Nested logical paths remain distinct even though storage uses content-addressed names.

Handoff, capture and close create no source view. Seal/reveal/comparison validate
through retained bytes. Successful SQL closure derives the same view from custody;
it no longer accepts an external source directory. Review initialization and source
access irreversibly reduce soft/hard core limits to zero in the restricted process.

## Copy and cleanup invariants

The complete [copy inventory and operation contract](../development/custodian-review.md#protected-source-access-and-copy-inventory-rv-09-01)
traces source, rights/snapshot/analysis proofs, A, raw response, reference, B, reports
and acknowledgments. Protected material stays in registered files or operation RAM.
There is no scratch tree, default temporary directory, memfd export or extra deletion
inventory. Output bytes still enter the existing exclusive durable intent/commit path.
Core dumps are disabled; callers must not persist raw content into unmanaged logs,
delivery archives, OS/hypervisor dumps or host copies.

Termination during validation leaves only original registered files. Termination
during output commitment or expiry remains governed by the existing lifecycle
intent/recovery protocol. Deletion checks the pinned inventory; unregistered files,
wrong owner/mode, links and corruption fail closed. No finally block is the safety
boundary. The original receipt and retention deadline never change.

## Verification and adversarial evidence

All fixtures and owner keys are synthetic. Actual Linux UID/GID 10002, zero capability
sets, NoNewPrivs, 0700/0600 and UID 10001 denial are required by the runtime harness.
The dedicated VMware guest and guest-local Docker endpoint are verified before
containers start. No real source or custodian is mounted.

The new restricted matrix covers:

- Read equivalence with original files through the accepted validator, real metadata,
  nested original paths, no write interface and zero core limits.
- Wrong tenant, namespace, attempt, generation, scope commitment, source hash, mode,
  symlink and hard-link rejection; original sentinel remains unchanged.
- Complete synthetic review with all default-temp creation forbidden, including
  handoff/capture with source-view construction explicitly forbidden.
- Real SIGKILL before view construction, during registered source reading, inside
  reference validation, before result commit, and after a registered source unlink.
- Before/after byte-hash inventories, unchanged default-temp sentinel, no extra event
  after failed validation, supervised cleanup completion and unchanged receipt/expiry.
- Natural expiry denies a previously created view and removes registered bytes.
- An explicit former-pattern negative control proves SIGKILL leaves a synthetic temp
  file; only its exact positively identified disposable target is then removed.
- Static guards reject persistent export primitives in review/source modules.

Existing restricted lifecycle/review, 35-scenario retention, genuine PostgreSQL
source-to-comparison, CP-01/02/03, concurrency/migration, worker/controller recovery,
frontend/browser, contracts/docs, dependency and secret checks remain required.
Pass/fail/skip counts and command timestamps come from actual local and final-head
CI results; none is inferred from an earlier report. Synthetic success establishes
the tested machinery, not analyzer accuracy, real blindness or official human gold.

| Recorded native verification | Actual result |
| --- | --- |
| Existing restricted lifecycle/review matrix at the recorded correction tree | 78 passed, 108.42s |
| RV-09-01 matrix with final read-only streams | 19 passed, 1 warning, 45.26s |
| Genuine scoped PostgreSQL execution/review | 5 passed, 1 warning, 126.25s |
| Windows unit suite after POSIX import-guard correction | 527 passed, 39 skipped, 338 warnings, 48.26s |

All five SIGKILL cases have separate before/after hash inventories and unchanged
sentinel/receipt/deadline evidence. Full-suite results, including an initial local
300-second command timeout and the preserved diagnostic rerun, are reported
separately in the consolidated evidence. A timeout is not counted as a pass.
Final-head CI reruns both restricted matrices, PostgreSQL, the full application,
browser and quality/security checks against the actual pushed commit.

## Compatibility and stop boundary

No analyzer/scorer, canonical identity, v2 evaluation schema, historical Store,
control-plane SQL, migration 0004, role or grant changes. No namespace migration,
new scratch service, privileged route, execution lease renewal or expiry extension.
See [ADR-0020](../adr/0020-post-execution-custody-authority.md#rv-09-01-eliminate-reconstructed-source-scratch)
and the [fresh execution runbook](../development/phase2-official-evidence.md).

Both original deadlines remain **2026-11-14 17:43:39 UTC** and
**2026-11-16 16:53:29 UTC**, including owner-managed copies. Historical custodians
are not mounted, modified or deleted. Physical deletion while powered off, failed
storage, OS/hypervisor paging and externally created copies remain operator/trusted
runtime obligations, not administrator-proof WORM or forensic erasure guarantees.

Historical 0/84 remains unchanged and is not measured 0% analyzer accuracy.
EVAL-ENTRY stays UNFROZEN with zero verified human-reviewed families. No real
acquisition, pilot, A/B generation, gold, reveal/scoring, merge, deployment or Phase 3.
Stop for final independent acceptance; no new real attempt is authorized here.
