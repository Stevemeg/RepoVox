# Retention runtime verification and reviewer handoff

Date: 2026-10-18 UTC. Disposition: synthetic operational correction verified;
independent engineering review and the real-custodian lifecycle remain required.
This report records synthetic operations only.
[Operational contract](../development/retention-runtime.md) ·
[accepted control plane](phase2ce-control-plane-verification.md) ·
[official readiness](../ai/evaluation-readiness.json).

## Baseline and change boundary

The branch is stacked on accepted control plane
`925752b8df38668349b9ef5a45a34cac7d948253`. Accepted analyzer/scorer remains
`711184e82128c7b0a6f3978cfc1cf13975db39ef`. No extraction, canonical identity,
verifier, scoring mathematics, v1/v2 evaluation contract, migration or role grant is
changed. Existing PRs remain unmerged. New code is operational tooling and synthetic
tests; no protected source, packet, reference, credential or screenshot enters Git.

The Dockerfile adds only the canonical retention files required by the new tests.
Pytest adds the repository root to its import path for trusted operational modules.
CI includes this follow-up branch and its stacked PR base. These infrastructure
changes are explicit and require review; an image built from this follow-up is not
silently substituted for an approved real-pilot engineering freeze.

## Evidence and environment

A new VMware Workstation Ubuntu 24.04 LTS VM was provisioned with its own virtual
disk, guest identity, SSH host key, local Docker daemon and storage. Configuration
disabled shared folders, Windows mounts, clipboard, drag-and-drop, USB attachment
and automatic VM startup. No unrelated VM, WSL distribution or shared Docker Desktop
service was started. No historical custodian was mounted.

The official Canonical image was checked against its signed SHA-256 manifest with
the published UEC signing fingerprint. Docker Engine was installed from Docker's
official Ubuntu repository after verifying its key. Actual guest hostname, OS,
daemon ID, Unix socket, data root, versions, initial empty inventories, mounts,
listeners and permissions were recorded privately before containers were created.
Observed runtime: Ubuntu 24.04.5, Engine 29.9.1, Compose v5.6.0, cgroup v2 and the
guest-local containerd image store. There is no TCP Docker API listener.

The VM uses two vCPUs, 2 GiB RAM and a new 30 GiB expandable disk within measured
host capacity. NAT is permitted for verified dependencies. Offline tests run without
a default guest route and with container network none. A DHCP-restored route was
caught by a precheck; a guest-only Netplan override now disables DHCP routes and
router advertisements. No shared host networking service was reconfigured.

Private command evidence retains exact arguments, input bytes, UTC times, exits,
stdout/stderr, hashes, image/volume IDs and filesystem inventories. Only sanitized
findings are in this document. The operating host and receipt custodian are trusted;
this is not administrator-proof WORM or cryptographic reviewer authentication.

## Corrections and retained failures

1. Image-inherited Compose labels had selected an incorrect container role. The
   validator now requires an independent provisioning plan/receipt and exact actual
   runtime properties. Ordinary Compose working-directory validation remains.
2. Windows default cp1252 decoding had changed original UTF-8 BOM bytes into
   mojibake. Transfer now uses canonical executable bytes and binary SHA-256 checks.
3. Docker 29 omitted an unset `Config.Cmd`. The exact unset case is supported;
   explicit command/entrypoint differences remain rejected.
4. A fixed 0.5-second probe preceded the first actual heartbeat. Startup now has a
   bounded six-second allowance and requires two fresh progressing observations.
   Three-second freshness and the original UTC retention deadline are unchanged.
5. An initial bounded observer used repeated `docker exec` Python processes and
   exhausted its startup budget under the same restricted container CPU quota.
   The successful observer reads the inspected process through guest-local `/proc`,
   checking cgroup, process birth, IDs, groups, capabilities, invocation and script.
   No container capability, quota, lease or retention deadline was relaxed.

The missed-expiry fixture declares a ten-second synthetic window before creation,
so startup, shutdown before expiry and restart after expiry are separately observed.
No already-created fixture or real custodian deadline was changed. This fixture
window does not alter the six-second startup limit or three-second freshness.

All original failure evidence, failed fixtures and intermediate command outcomes
remain preserved. Provisioning also retained GPG-agent, PCIe allocation and build
reference errors before successful setup. A later evidence-export assertion was
corrected to compare intentionally invalid identity labels against their original
creation inspection rather than pretend that adversarial fixtures were valid.
No runtime result was rerun merely to relabel the same failed bytes as successful.

## Actual verification

- Operational host suite: **53 passed**, including original byte/identity controls,
  bounded startup, late/missing/repeated/forged heartbeat, process/script/privilege
  rejection and exact unset-command behavior.
- Complete Windows unit suite: **527 passed, 36 skipped**, 338 warnings, **51.01s**.
  The skips are actual POSIX custody/freeze cases and are not counted as passes.
- Ruff and formatting: passed, **109 files** checked for formatting. Mypy: passed,
  **57 application source files**. Untyped operational code is covered by lint and
  synthetic tests; this does not claim mypy coverage of those tools.
- Linux Docker retention matrix: **35 passed**, exit 0, **169.27s**, from
  **2026-10-18 13:45:53.978964 UTC** through **13:48:43.244463 UTC**.
  Original stdout/stderr commitments and source hashes match the retained run plan.

The 35 runtime cases include valid standalone and actual Compose identities;
inherited/forged/missing/conflicting labels; receipt, image, volume, mount and
privilege substitution; canonical byte transfer and target-shell checks; corrupt
bytes/BOM/shebang/syntax; fresh loop/process evidence; stalled and stale health;
actual UID 10001 read/enumeration denial; concurrent lock denial; pre-expiry byte
preservation; exact post-expiry deletion with an untouched unrelated sentinel;
missed-expiry restart; duplicate/idempotent receipt preservation; immediate exit;
extra files/directories; changed bytes; links and forged absolute/parent paths.
Filesystem effects, hashes and original deadlines were checked, not inferred from
log messages. Every watchdog from the successful run was stopped and checked
against its recorded creation identity. Failed-run evidence remains separate.

Fresh disposable PostgreSQL 16.13, Redis and object storage used a new namespace,
database, credentials, network and volumes inside the independent guest. Exact
container IDs, image IDs, mounts, source initialization script and credential
binding were inspected before migration. A stricter read-only/capability-drop
override was applied to the never-started disposable migration service; no existing
database or shared service was migrated. Setup transcripts retain unsupported
Compose flags and a short-ID comparison failure; supported commands and fully
resolved IDs corrected those wrappers without weakening a grant or SQL predicate.

- Full Linux `docker compose ... run --rm --no-deps tests pytest -q --tb=short`:
  **633 passed, 2 skipped**, 346 warnings, **351.60s**, completed
  **2026-10-18 14:11:24 UTC**. Both skips are Windows-only controls covered by the
  host run. The suite includes actual PostgreSQL READ COMMITTED concurrency/roles,
  CP-01 cancellation/fencing, CP-02 scope, CP-03 publication, ordinary SaaS behavior,
  original analysis and v1/v2 evaluation compatibility, upgrade and empty rollback,
  and populated-ledger rollback refusal.
- Original supplemental source code, copied alone into a read-only synthetic
  mount: **6 passed**, 2 warnings, **86.71s**. This covers genuine Python/JavaScript/
  TypeScript static pipelines, exact selected-scope exclusion, actual worker-process
  restart and ordinary work after pilot invalidation, plus an old-draft 0004 DB.
  `upgrade head` left its old function unchanged, as required; that is not a fix.
- Original actual controller-process crash rehearsal: **2 passed**, **14.37s**.
  Crashes before/after invalidation could not invoke restoration prematurely;
  recovery reached durable INVALIDATED, generation 2, with zero acquisition.
- Exact unnormalized stored CP-03 body equals the accepted SQL. Its complete stored
  function definition SHA-256 is
  `83d8462906dc5203d6fccfe6a3433b1572669606d9257a4687a423d339f6579f`.
  All four pilot tables have forced RLS. Ordinary app/worker roles lack protected
  register/claim EXECUTE; runtime capability groups have no superuser/RLS bypass/
  role/database-creation privilege. No public grant was introduced.
- Python dependency audit: no known vulnerabilities; the local RepoVox package is
  explicitly unaudited because it is unavailable on PyPI.
- Documentation, contracts and cost checks passed. Documentation tooling tests:
  **32 passed** in the earlier coordinated run. New documents have also passed the
  current link/schema/phase-gate validator.

Final-head CI, frontend/browser results, secret scanning and attribution are
recorded on the draft PR after publication; earlier accepted-head CI is not a
substitute. Final local preservation verified 315 historical host files, 91 failed-
attempt files and all seven original operational entries unchanged. The 49-file
engineering index identifies exactly two intentional test-infrastructure changes:
Dockerfile and pytest configuration. Accepted production/evaluation/SQL source has
an empty diff. Live old custody was not mounted or reattested.

## Review map and remaining gates

Review identity and exact matching in `tools/phase2_retention_identity.py`; the new
bounded state machine in `tools/phase2_retention_readiness.py`; actual trusted-host
observation in `tools/phase2_retention_observer.py`; binary packaging in
`tools/phase2_retention_bundle.py`; and the target scripts under
`infrastructure/retention/`. Deterministic controls live in
`tests/unit/test_retention_identity.py` and `test_retention_readiness.py`.
`tests/operational/retention_runtime.py` contains the explicit actual Docker matrix.

The watchdog accepts only a completed synthetic inventory. It deliberately rejects
real activation and does not support an actively growing custodian. Passing these
tests does not authorize removing that guard. A supported real-custodian lifecycle,
independent review and a verified fresh retention mechanism are required before
protected real evidence is stored. No real pilot attempt, acquisition, A/B packet,
reference, reveal, score or Phase 3 has occurred in this correction.

Original custody expiries remain **2026-11-14 17:43:39 UTC** and
**2026-11-16 16:53:29 UTC**, including owner-managed host copies and withdrawal.
This VM neither activates their watchdogs nor reattests their current live contents.
Historical **0/84** remains unchanged; it is not a measured 0% analyzer accuracy.
Official EVAL-ENTRY remains UNFROZEN, with no genuine human reviewer appointed and
all official approved counts zero. Engineering and AI exploratory references cannot
satisfy the human, rights, authorship, protected-corpus and freeze requirements.
