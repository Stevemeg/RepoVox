# Control-plane correction reviewer handoff

Independent engineering review is required. Synthetic proof does not establish real
pilot completion or accuracy. No blind execution or packet reuse follows from this
review alone.

## Review entry points

- [ADR-0017](../adr/0017-pilot-control-plane-safety.md): incident cause and decisions.
- [Contract](../development/pilot-control-plane.md): roles, transaction ordering,
  source enforcement, recovery and explicit limits.
- [Migration](../../apps/api/migrations/versions/0004_pilot_control.py) and
  [SQL gates/grants](../../apps/api/migrations/pilot_control.sql): original delegates,
  auditability, terminal/fence predicates and empty-ledger-only rollback.
- [Controller](../../apps/api/repovox/pilot/control.py): registration, atomic admission,
  status and abort-before-restoration; no Docker lifecycle calls.
- [Executor](../../apps/api/repovox/pilot/execution.py): tenant-bound authenticated route,
  engine inventory, mandatory adapter, fenced storage and direct outbox delivery.
- [Manifest](../../apps/api/repovox/pilot/contracts.py): canonical commitments,
  exact pin/file hashes and source/context roles.
- [Synthetic integration](../../tests/integration/test_pilot_control.py),
  [migration proof](../../tests/integration/test_pilot_migration.py) and
  [source-scope negatives](../../tests/unit/test_pilot_scope.py).
- [Verification](phase2ce-control-plane-verification.md): commands, failures,
  results, compatibility and private-evidence boundary.

## Independent questions

1. Can a stale generation, stage fence, legacy retry or broker notification obtain
   another pilot lease after invalidation? Inspect claims, recovery and publication.
2. Can ordinary Celery execution or generic admission bypass the binding, authenticated
   role, exact approved scope or original-file hashes?
3. Are quota/attempt/job locks sufficient for READ COMMITTED, and are publication and
   cancellation linearized without claiming atomic external I/O?
4. Can a missing adapter publish a filter result or permit excluded semantic parsing?
   Do the actual synthetic pipeline and fault tests detect that regression?
5. Are private delegates unavailable to runtime logins, terminal records immutable,
   tenant checks enforced and grants least-privilege?
6. Does rollback preserve original procedures and refuse a populated ledger?
7. Are routine retry/storage/security/legacy evaluator behavior and final-head CI
   intact, with no protected records in Git or public artifacts?

The final draft PR records exact head, changed files, final-head CI and attribution
audit. Review needs no historical references or Package B. No expected answers from
those materials were used in tests.

## Adversarial proof map

All cases below use synthetic source, new test credentials and disposable services.
The integration file linked above contains the named tests; scope negatives and
rollback live in their separately linked files. The suite collects 43 new cases
(13 scope unit cases and 30 database/broker/migration cases).

| Required scenario | Test or tests | Observable requirement |
| --- | --- | --- |
| 1. Timeout and delayed retry | `timeout_then_restoration_and_stale_outbox` | One acquisition call; terminal attempt; no second lease or artifact |
| 2. Restart with pending outbox | `pending_and_already_published_events_after_abort` | Dedicated delivery and ordinary dispatch cannot revive work |
| 3. Broker redelivery | `real_celery_restart_redelivery_cannot_revive_invalidated_pilot` | Real isolated worker consumes stale message, audits rejection and executes no analysis |
| 4. Concurrent claims | `two_workers_only_one_claim` | Exactly one independent connection receives a lease |
| 5. Cancellation versus admission | `cancellation_races_admission` | Either ordered outcome leaves a terminal cohort and no executable stage |
| 6. Cancellation versus stage publication | `publication_races_cancellation`, `cancellation_commits_before_actual_stage_publication` | Cancellation-first prevents accepted output; receipt alone cannot publish |
| 7. Stale lease/generation | `stale_fence_blocks_scope_writes_and_publication`, `stage_receipt_does_not_survive_new_generation` | Stale scope, receipt and completion are denied |
| 8. Controller recovery | `legacy_retry_wait_cannot_survive_reconciliation`, `expired_lease_recovery_invalidates` | Recovery invalidates before retry promotion |
| 9. Publication after invalidation | `pending_and_already_published_events_after_abort` | Conditional outbox publication returns false |
| 10. Already published notification | `timeout_then_restoration_and_stale_outbox`, real Celery case | Delivered stage ID obtains no new lease |
| 11. In-flight external request | `inflight_request_finishes_after_cancel` | Request may return; subsequent storage/publication cannot succeed |
| 12. Missing scope adapter | `retry_missing_adapter_rejected_at_filter`, `generic_runner_without_scope_guard_cannot_publish` | No unscoped filter output or later semantic stage |
| 13. Excluded test file | `actual_pipeline_never_parses_excluded_test`, scope unit case | Selected symbol exists; excluded sentinel never enters canonical facts |
| 14. Tampered/cross-family manifest | `forged_or_cross_tenant_execution`, `selected_hash_tampering_fails_before_archive_publication`, scope negatives | Wrong family, hash, pin, bytes or role fails closed |
| 15. Cross-tenant execution | `forged_or_cross_tenant_execution`, `role_grants_and_tenant_control` | Other tenant obtains no lease or authority |
| 16. Missing/forged authorization | `unauthenticated_route_and_fake_worker_name`, `manifest_commitment_and_engine_missing_fail_closed` | Worker labels cannot grant authority; missing engine attestation fails before I/O |
| 17. Ordinary restart after abort | Real Celery case, `controller_abort_precedes_restoration`, `restore_callback_never_runs_when_abort_outcome_unknown` | Restoration requires confirmed terminal state; stale tasks remain denied |
| 18. Ordinary workload compatibility | `ordinary_work_continues_after_pilot_abort`, existing integration suite | Nonpilot transient retries still advance normally |
| 19. Migration and grants | `role_grants_and_tenant_control`, migration proof | No runtime table/delegate/evaluation privilege; exact empty rollback and guarded populated rollback |
| 20. Duplicate terminal events | `terminal_generation_and_idempotent_invalidation` | One generation increment; immutable terminal metadata and preserved audit |

The real Celery case explicitly seeds and asserts the legacy `retry_wait` state after
a timed-out synthetic request, durably aborts before restoration, then delivers the
original outbox stage notification to the restored worker. That single scenario
reproduces the incident sequence without a second analysis stage or real repository.

## Limits and next gate

Review trusted service/host assumptions, fixed expiry versus controller liveness,
upload-orphan handling and physical quiescence separately. Do not interpret
`EXECUTION_CLOSED` as evaluator acceptance. Frozen analyzer/scorer components stay at
the accepted revision; future control-plane deployment/freeze and any real attempt
need separate owner authorization after this review.
