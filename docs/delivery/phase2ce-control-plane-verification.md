# Phase 2C-E control-plane verification

Status: implemented for independent engineering review. This is not authorization
for another pilot. Final-head CI and PR/head identifiers are recorded in the draft
PR and final reviewer handoff after publication; independent acceptance is pending.

## Baseline and scope

Verified local/remote base and draft PR 7 head:
`711184e82128c7b0a6f3978cfc1cf13975db39ef`. Correction branch:
`phase2/pilot-control-plane-safety`, stacked on `phase2/source-fact-v2-evaluation`.
The existing owner Git identity is associated with Stevemeg. No history rewrite,
merge, private evidence upload or analyzer/scorer change is authorized.

The private read-only investigation supports CP-01 (resumable database work exposed
by unconditional service restoration) and CP-02 (ordinary runner lacked scope).
Initial manual execution had no broker ACK; exact later message/ACK IDs and the
transport subphase remain unknown. Public engineering evidence is synthetic only.

## Implementation and security

[ADR-0017](../adr/0017-pilot-control-plane-safety.md) and
[contract](../development/pilot-control-plane.md) define transactions, roles,
source validation, failure recovery, limitations and rollback. Migration 0004 wraps
control procedures, retains private original delegates and adds no gold/prediction
table. Non-login capability groups create no running service. The direct authenticated
route cannot inherit ordinary worker fallback. Runtime identity checks reject
superuser, RLS bypass, role/database creation and internal executor membership.

Only new explicitly disposable Compose resources are used for local integration:
project `repovox-cp-48cab4a0da10`. Its independently generated credentials and raw
command outputs remain outside Git. Existing projects and custodian volumes are not
mounted, restarted, migrated or reset. Before test commands, the local harness checks
the PostgreSQL container's Compose label and project-specific volume identities.

## Commands and results

Verification ran on 2026-10-16/17 UTC with locked dependencies. The disposable
harness expands to
`docker compose -p repovox-cp-48cab4a0da10 --env-file PRIVATE_TEST_ENV -f docker-compose.yml`
and `run --rm --no-deps tests ...`. Early runs added read-only Windows source/test
bind mounts; the final run uses the ordinary built image without those mounts.
Database labels/volumes are verified before either form. No private test credential
or environment file is committed. The image is built with
`docker compose ... build tests migrate`; resource/security options are unchanged.

- `uv run pytest tests/unit -q`: 474 passed, 36 Windows/POSIX platform skips,
  338 deprecation warnings, 35.21 seconds on the initial host full run.
- `uv run mypy`: passed, 57 source files on that run.
- `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` and
  `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py`:
  passed after final source/test edits; 102 files formatted. Final mypy also passed.
- Disposable `0004 -> 0003 -> 0004` round trip: passed.
- Focused synthetic integration initial broad run: 29 passed, 1 failed. Failure was
  permission-test introspection resolving the already protected `evaluation` schema;
  it was corrected to assert absence of schema USAGE, preserving denial.
- Initial full Linux `pytest -q --tb=short`: 566 passed, 2 platform skips,
  346 warnings, 209.09 seconds, completed 2026-10-16 16:53:58 UTC (before final
  runtime-identity hardening and final test refinements).
- Repeated Windows-bind Linux full suite: 563 passed, 3 failed, 2 platform skips,
  346 warnings, 624.34 seconds; completed 2026-10-17 02:02:16 UTC. Failures:
  existing worker-fault checkpoint timeout, existing ordinary Celery delivery
  deadline and pilot Celery rejection-observation deadline. Exact worker stderr
  was discarded by these cases; the startup cause is unresolved. A read-only
  PostgreSQL probe observed filesystem synchronization waits. No deadline,
  assertion, database durability or resource limit was relaxed.
- Final ordinary-image `pytest -q --tb=short`: **566 passed, 2 platform skips**,
  346 warnings, **172.03 seconds**; completed **2026-10-17 02:10:26 UTC**.
  All 43 new synthetic cases passed, including migration/role/concurrency proof and
  the complete legacy retry/timeout/restoration/outbox/stale-claim scenario. The
  two skips are explicitly Windows-only fail-closed checks covered on the host.
  The successful run uses the same caps, quotas, leases and test deadlines; earlier
  failures remain preserved, rather than being relabeled as successful runs.
- `uv run python tools/check_docs.py`: 31 required paths, 75 Markdown files,
  487 local links/anchors, 32 JSON files; all contract/mutation checks passed.
- `uv run python tools/cost_model.py --check`: passed (planning estimates only).
- `uv run python -m unittest discover -s tools -p 'test_*.py' -v`: 32 passed,
  1.772 seconds in the final documentation run.
- `uv run python tools/phase1_contracts.py --check`,
  `uv run python tools/phase2_contracts.py --check` and
  `uv run python tools/phase2_v2_contracts.py --check`: passed.
- `uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json`
  and `uv run python tools/phase2_preparation.py --catalog docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json --output docs/ai/evaluation-readiness.json --check`:
  passed; corpus remains UNFROZEN with zero official human-reviewed families.
- `uv run pip-audit --local`: no known vulnerabilities; local RepoVox package
  unavailable on PyPI is explicitly unaudited. Dependency files are unchanged.
- Windows `npm --prefix apps/web run lint`, `run typecheck`, `run build`:
  passed. `npm --prefix apps/web audit --audit-level=high`: zero vulnerabilities.
  `npm --prefix apps/web test` failed to start all three Vitest worker processes
  (60.14 seconds; no tests ran). Linux CI must independently pass these unchanged
  frontend tests and browser regressions; this local failure is not a pass.

Final-head CI must independently pass all existing workflow jobs; its exact run is
recorded in the PR. Skipped checks are never represented as passing. New tests cover
actual READ COMMITTED connections,
simultaneous claims, admission/cancellation races, a deterministic publication race,
in-flight cancellation, legacy retry recovery, missing adapter, source tampering,
cross-tenant/family/generation/hash claims, immutable records, nonprivileged grants,
ordinary workload compatibility and real isolated Celery redelivery.
The [reviewer handoff](phase2ce-control-plane-reviewer-handoff.md#adversarial-proof-map)
maps all twenty required scenarios to 43 newly collected synthetic cases.

## Failures corrected during engineering

1. Empty-ledger downgrade initially lacked the existing executor's temporary schema
   CREATE grant while restoring original function definitions. The migration now
   grants it only for that migration transaction and revokes it afterward. No runtime
   role or Linux capability was elevated.
2. A legacy-retry fault fixture initially omitted its tenant context, so it had not
   actually seeded `retry_wait`. The fixture now binds its synthetic owner and asserts
   the injected state before invoking recovery; no application gate was weakened.
3. Permission introspection initially raised schema denial rather than returning a
   boolean. The assertion now checks the actual denied schema privilege directly.
4. Initial formatting/type errors in new code were corrected without changing the
   frozen analyzer's annotations or implementation; its storage dependency is bridged
   by the new adapter's complete read/write/delete protocol.
5. Final review corrected closure audit metadata to record the new terminal
   generation, with an assertion against durable status. The admission race now
   creates a new job/binding under contention, rather than testing only replay.

## Compatibility, custody and limitations

Analysis 2.2 reader, 2.3 extraction, static rules, canonical facts, v1/v2 evaluation
and schemas are outside the changed-file set. Their existing tests remain required.
Ordinary 0003 readers remain supported; pilot execution requires 0004. Original
migration files and historical rows are unchanged. Populated-ledger rollback refuses
to delete lineage. Tests use separate databases even for rollback verification.

No real acquisition, Stage E2 attempt, Package A/B production, packet reuse,
reference authoring/capture, reveal, scoring or Phase 3 occurred. Historical 0/84,
original sealed records and official UNFROZEN/human-review status remain unchanged.
Read-only hashing matched all 315 host-side files recorded by the incident intake:
zero changed or missing files. This is host-file integrity evidence, not a new
inspection/authentication of sealed custodian contents. No custodian was mounted.
Custodian expiry stays **2026-11-14 17:43:39 UTC**; withdrawal and owner-managed
host-copy responsibilities are unchanged. Engineering has no real custody mount.

Remaining limits: approved operator/host and service credentials are trusted; scope
receipts are execution assertions, not independent semantic proof. Fixed 45-minute
authorization expiry is not a renewable controller heartbeat. In-flight network/upload
effects are not instantly reversible; no accepted pointer may publish after cancellation.
Physical quiescence is separate from durable invalidation. Independent review is required
before any future owner decision on execution or reuse of retained packets.

## CP-03 focused correction

Independent review identified missing event-level eligibility in `rv.pilot_published`
at `e97548769b21f9484a095168e78348678d458d7d`. Local/remote branch and PR 8 were
verified at that exact head, still draft/unmerged against accepted `711184e`.
No analyzer/scorer or evaluation-contract change is included in this correction.

Reproduction used only fresh disposable Compose project
`repovox-cp03-8f5f4fe0d64e`, independent credentials and ordinary built images, with
no incident-project or custodian mount. Command outputs, stderr, exit codes and UTC
timestamps remain in an owner-only engineering directory outside Git.

- Original three regressions (`future`, `published`, `running`): **3 expected
  failures**, 3.84 seconds, completed 2026-10-17 11:22:09 UTC. The reviewed function
  incorrectly returned true for all three.
- Expanded committed-readback reproduction against that original database function:
  **6 expected failures, 3 passed**, 22.93 seconds, completed 2026-10-17
  11:24:39 UTC. Future/running/pending/mismatched-stage/terminal-job events acquired
  publication timestamps; an already-published event incorrectly reported a new
  publication. Canceled, expired and cross-attempt negative controls passed.
  The test commits the call before checking both result and stored timestamp.
- Exact reproduction command: `docker compose -p repovox-cp03-8f5f4fe0d64e --env-file PRIVATE_TEST_ENV -f docker-compose.yml run --rm --no-deps tests pytest -q tests/integration/test_pilot_control.py -k publication_rechecks_event_eligibility --tb=short`.
- One rebuild failed with a GHCR TLS handshake timeout at 2026-10-17 11:26:40 UTC,
  before the migration/test commands. An identical build succeeded at 11:27:31 UTC;
  no image/tool version was substituted. Both outcomes and stderr are preserved.
- Corrected focused run: **14 passed, 29 deselected**, 22.17 seconds, completed
  **2026-10-17 11:28:25 UTC**. Command:
  `docker compose ... run --rm --no-deps tests pytest -q tests/integration/test_pilot_control.py -k "publication_rechecks or concurrent_publication" --tb=short`.
- Final full regression: **580 passed, 2 skipped**, 346 warnings, **193.07 seconds**,
  completed **2026-10-17 11:31:47 UTC**. Command:
  `docker compose ... run --rm --no-deps tests pytest -q --tb=short`.
  This includes all 57 control-plane/scope cases against the accepted base, real
  READ COMMITTED concurrency/roles, migration upgrade/rollback guards, ordinary SaaS,
  historical v1/v2 contracts/scorers and source-provenance/security regressions.
  Both skips are explicitly Windows-only checks; they are not counted as passing.
- Ruff lint/format (102 files), mypy (57 source files), documentation and all three
  phase contract checks passed. One initial long test SQL literal was split to meet
  the unchanged Ruff limit. The SQL diff audit confirms only `rv.pilot_published`
  changed; all other procedures, schema definitions and grants are identical.

The database correction touches only `rv.pilot_published`. Locks follow owner quota,
attempt, job, stage, event order. State/association/readiness are checked under these
locks; the conditional update rechecks current event identity, null publication,
due time and live attempt/job deadlines. Explicitly acquiring the event lock before
the time predicate also covers a `SELECT FOR UPDATE` holder that creates no new
tuple while authorization expires. True means exactly one new publication; false
preserves an existing timestamp. The independent stage claim remains mandatory.
Ordinary outbox delegates and all grants/signatures are unchanged.

Migration 0004 is corrected in place because it remains an unmerged, undeployed
draft used only in disposable environments. No 0005 is needed for this authorized
scope. Previously applied draft databases require recreation or a separately
reviewed forward migration; `upgrade head` alone cannot reload edited SQL. For this
test database only, reproduction logs were preserved, synthetic fixture rows reset,
and empty-ledger downgrade/re-upgrade applied the corrected SQL. The existing
populated-ledger refusal remains part of the required regression suite.

Fourteen new PostgreSQL cases cover nine eligibility negatives, two concurrent
publication/delivery scenarios and three observed lock-wait races. Expiry clock
fixtures use disposable-administrator transaction-local replication mode; no runtime
role, trigger or production permission is changed. The expiry race waits for the
actual shortened fixture deadline while publication is blocked on an unchanged
event tuple. No runtime timeouts or resource limits are relaxed.

The exact final-head CI run and attribution/secret-scan audit are recorded in the
PR before the independent re-review handoff. Existing local/CI results above describe the
original correction and are not substituted for CP-03 final-head verification.
