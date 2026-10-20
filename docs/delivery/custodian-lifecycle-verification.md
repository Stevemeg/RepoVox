# Growing custodian independent-review handoff

Date: 2026-10-19. Status: engineering ready for independent review; no independent acceptance
or real activation. This additive correction follows draft PR #9 at
`8d8290dd4761f03a43a9be93cba160e36c86cdd9` without rewriting its history.

Root cause: the earlier watchdog required a fixed completed inventory, while the
historical Store could append evidence without a durable retention registration.
Neither provided a growing-write/expiry recovery protocol. The new
[normative lifecycle](../development/custodian-lifecycle.md) and
[ADR-0019](../adr/0019-growing-evaluation-custodian.md) define that protocol.

## Review map

- `tools/phase2_custodian_lifecycle.py`: plan/receipt pins, irreversible states,
  SQLite intent/recovery, exclusive byte writes, locks, deletion and metadata checks.
- `tools/phase2_custodian_adapter.py`: tenant-bound Store-like API, genuine
  authenticated claim gate, event batch registration, accepted prereveal/reveal and
  comparison validation; no new SQL authority or public service.
- `tools/phase2_custodian_watchdog.py`: singleton runtime, actual progress validation,
  fixed deadline, restart recovery and unavailable/error behavior.
- `tests/unit/test_custodian_lifecycle.py`: actual restricted Linux processes,
  SQLite/fsync/flock, kill points, concurrency, inventory attacks, original synthetic
  v2 contract interoperability and no real reference data.
- `tests/operational/custodian_runtime.py`: explicit isolated Docker/image/mount/
  identity checks, new synthetic volume, actual UID 10001 denial and 10002 read,
  exact filesystem cleanup with unrelated sentinel, private command/identity logs.
- `tests/integration/test_custodian_gate.py`: actual supported PostgreSQL claim,
  wrong attempt/manifest and cancellation rejection; zero source acquisition.

CI adds a separate restricted UID 10002 run because ordinary app UID 10001 must not
execute or falsely pass custodian-only tests. Standard Windows/noncustodian skips
remain actual skips. The original fixed-inventory 35-case matrix is unchanged.

## Reproduction and evidence scope

First positively identify the dedicated VMware VM, its separate disk, guest and
Docker daemon/storage/network. Never start Docker Desktop or shared services. Use
only new disposable synthetic namespaces with no real custody or credentials.
Build the trusted test image from the exact review head using locked dependencies.
Then, on the verified guest-local Docker host, run:

```sh
sudo python3 tests/operational/custodian_runtime.py "$PWD" "$TEST_IMAGE_ID" \
  "$VERIFIED_DAEMON_ID" "/opt/synthetic-custodian-proof-$UNIQUE_ID"
docker run --rm --user 10002:10002 --cap-drop ALL \
  --security-opt no-new-privileges:true --read-only --network none \
  --memory 256m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m "$TEST_IMAGE_ID" \
  pytest -q tests/unit/test_custodian_lifecycle.py
```

The Docker host operator is trusted and must inspect the planned targets first.
Only the explicit new synthetic volume is initialized; no volume discovery cleanup
or recursive custody deletion occurs. Raw evidence and all failed iterations stay
private outside Git/CI. Synthetic source is safe for CI; no real pilot packet is
mounted or published. Exact commands and original failures are retained privately;
final-head CI is recorded on draft PR #9 after publication, never inferred from an
earlier green head.

## Actual results and preserved corrections

The dedicated VMware guest remained Ubuntu 24.04.5 with its original independent
Docker 29.9.1 daemon, separate disk and no shared Docker Desktop/WSL/custody mount.
Source/config bytes, actual image/container IDs, mounts, UID/GID, zero capabilities,
NoNewPrivs, 0700/0600 and offline networking were checked.

- Final growing lifecycle: **42 passed, no skips, 18.66s**, in restricted actual
  UID/GID 10002:10002 containers with 256 MB, one CPU, 64 PIDs and 64 MB tmpfs.
  Includes actual ENOSPC, write/expiry/process crashes, metadata/path attacks,
  duplicate watchdogs, live activation, restart, full synthetic v2 protocol and
  exact original bytes. Separate containers proved UID 10001 enumeration/read
  denial and UID 10002 access/cleanup.
- Unchanged fixed-inventory retention matrix: **35 passed** again, including actual
  expiry, sentinel, recovery and identity adversaries. Its original guard remains.
- Full local service suite at the 38-custodian-fixture point: **634 passed, 40 skipped,
  346 warnings, 331.51s**. The 38 custodian skips were separately tested as UID 10002,
  not counted as passes; two remaining skips are Windows controls. Four additional
  custodian cases pass in the final 42-case runtime. Final CI reruns all final source
  and separately runs UID 10002 on bounded tmpfs.
- Original supplemental synthetic pipelines, actual worker restart and old-0004
  no-op: **6 passed**, 2 warnings, **99.49s**. Controller-process crash: **2 passed**,
  **17.87s**, zero acquisition and restoration only after durable terminal reread.
- Windows units: **527 passed, 37 skipped**, 338 warnings, **24.05s**. The new POSIX
  module is one actual Windows collection skip. Lint/format, mypy (57 app files),
  docs/contracts/cost/official readiness checks and 32 doc-tool tests pass. Dependency
  audit found no known vulnerability; local RepoVox is explicitly unaudited.
- The same dedicated VM was actually shut down and restarted with a new synthetic
  committed namespace. The initial 45-second SSH readiness probe failed. Its failure
  was preserved, not relabeled. After the same guest became accessible, pinned host,
  daemon, namespace and unchanged expiry were rechecked. Cleanup observed the missed
  expiry, removed all registered bytes, preserved the sentinel and confirmed the
  unchanged receipt. No routine service was restored. This proves recovery after
  missed expiry, not on-time deletion while powered off, an SSH startup SLO or
  physical power-cut durability.

Final growing proof archive SHA-256:
`b496c46f0c6d44e64a9f6380871849db49b23095902d34e931671d017ea3b4f0`.
It contains only synthetic private operational evidence. Commands/stdout/stderr,
heartbeats, process capabilities, source commitments and actual inventory effects
remain outside Git. Earlier iterations preserve fixture-hook, imported-fixture,
negative-check ordering and lock-contention failures. A single namespace-lock
acquisition is now bounded to one second; watchdog admission remains nonblocking.
No expiry, authorization or health bound was extended. SQLite EXTRA plus readback
replaces the initial FULL prototype under the DELETE-journal durability assumptions.
No real attempt was used as a test.

Read-only preservation matched 315 historical host files, 91 failed-attempt files,
seven original operational sources and all 185 prior consolidated evidence files.
All 43 original E1 tree/screen records, ten selected original file hashes, licenses
and exact proposed scopes were reconciled. Excluded hashes remain retained pinned
metadata, not freshly acquired files. The private execution manifest is explicitly
non-executable pending engineering review and fresh owner confirmation. No real
A/B packet or accuracy result was created.

## Compatibility and limits

Accepted analyzer/scorer `711184e82128c7b0a6f3978cfc1cf13975db39ef`, control-plane SQL
`925752b8df38668349b9ef5a45a34cac7d948253`, migration 0004, roles, v1/v2 mathematical
contracts and historical Store remain unchanged. SQLite is a namespace-local durable
ledger, not an application schema migration. No persistent pilot DB is modified.
No old custodian is migrated, no packet reused and no actual gold authored.

This is cooperative trusted-custodian security, not malicious-host/UID resistance
or forensic erasure. A powered-off/unavailable host, blocked writer, corruption,
unexpected file, full disk or failed unlink prevents guaranteed physical deletion;
it blocks readiness and requires operator intervention at the original deadline.
Do not claim a passing heartbeat supersedes those obligations or that the namespace
automatically covers external source/object-storage/host copies.

See [official evidence and fresh-attempt runbook](../development/phase2-official-evidence.md).
Independent security/engineering acceptance and a fresh owner execution decision
remain mandatory. No real acquisition, prediction, B reveal, merge or Phase 3 is
authorized by this review handoff. Official EVAL-ENTRY remains UNFROZEN with zero
verified human-reviewed families and pending rights/reviewer/corpus evidence.
