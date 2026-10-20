# AWS-10-01 cleanup execution result correction

Date: 2026-10-20. Status: implementation proposed for independent re-review.
Reviewed baseline: `bb53ae120d3d2df1011ed45933d3a041a5b50ab1`.
Branch: `phase2/aws-retention-integration`; continue draft PR #10 stacked on
unchanged draft PR #9 at `6b412e930dfcfd6b771a457d27633f5f7d5ac8e5`.
Final commit and final-head CI are recorded in PR #10 after verification.

## Finding and bounded correction

`reconcile()` always returned `status: VERIFYING`, including when a denied,
throttled or unavailable provider operation was durably recorded as INCOMPLETE.
It also left the actual registry in CLEANING. The recovery test expected that
misleading result. Four new contract assertions failed against the original code:
AccessDenied, RequestLimitExceeded, ServiceUnavailable and successful requests
awaiting independent verification. Original failure output is preserved privately.

Replace the unversioned ambiguous return with `aws-cleanup-execution-result-1.0`.
See the [normative field contract](../operations/aws-retention-integration.md).
Any failed operation yields `outcome: INCOMPLETE`; otherwise return
`AWAITING_INDEPENDENT_VERIFICATION`. Return separate requested/incomplete counts,
their total, generation and validated lifecycle state CLEANING. Every result has
`deletion_verified: false`. There is no `status` compatibility alias and no result
that proves deletion. `CleanupExecutionResult` makes the output shape and literal
false explicit to typed callers. Only existing tests call this offline adapter;
those callers are updated together. Deployment entry points remain refusing.

A final read-only claim check prevents returning a result for a lease that expired
or was replaced after the last progress write; it also covers empty ticks. A stale
claim or registry/progress failure propagates, without falsely returning a valid
result. This adds no lease extension, claim ownership change or lifecycle transition.
The lifecycle field is an observation at the final check, not a race-free promise
about later state. No new database, authorization or cleanup architecture is added.

## Exact changed files

- `tools/phase2_aws_cleanup.py`: explicit typed/versioned execution result and final claim check.
- `tests/unit/test_aws_recovery.py`: corrected expectations and adversarial result/lease tests.
- `docs/operations/aws-retention-integration.md`: outcome/lifecycle distinction and consumer rules.
- `docs/delivery/aws-10-01-cleanup-result-correction.md`: this correction, evidence and limits.

## Verification

All provider operations are botocore Stubber simulations with explicit dummy
credentials and the existing unconditional network refusal. Durable local fixture
checks use disposable SQLite; they are not AWS/DynamoDB isolation proof.

Regression cases cover denied, throttled and unavailable operations; partial failure
in both orders; successful requests requiring separate absence; empty ticks; stale
claims before a request, after durable progress and on an empty tick; and restart
after interrupted progress acknowledgment. Counts are checked against actual
durable progress rows. Root bytes/expiry stay unchanged on partial failure.

Local results:

- Baseline reproduction: **4 expected failures**, 10 deselected; these are retained failures, not passes.
- Corrected recovery/registry/service-signature focus: **47 passed**, no skips, 27.38 seconds.
- Entire AWS plus accepted offline cloud suites: **226 passed**, no skips, 46.97 seconds.
- Full Windows unit suite: **753 passed, 39 skipped**, 338 warnings, 67.70 seconds.
- Ruff and formatting (143 files), unchanged strict application mypy (57 files),
  additional AWS script body checks (9 files), documentation (98 Markdown/615
  links/36 JSON), generated infrastructure drift and unchanged budget checks pass.
- Adding a return type initially exposed incomplete parameter annotations in mypy;
  explicit parameter types corrected this without relaxing the gate.

Exact commands:

```text
pytest tests/unit/test_aws_recovery.py tests/unit/test_aws_registry.py tests/unit/test_aws_security.py -q
pytest tests/unit/test_aws_adapters.py tests/unit/test_aws_registry.py tests/unit/test_aws_security.py tests/unit/test_aws_recovery.py tests/unit/test_aws_budget_creation.py tests/unit/test_cloud_retention_model.py tests/unit/test_cloud_retention_corrections.py tests/unit/test_cloud_verifier_coverage.py -q
pytest tests/unit -q
ruff check apps/api tests tools/phase1*.py tools/phase2*.py
ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py
mypy
mypy --explicit-package-bases --follow-imports silent --ignore-missing-imports --allow-untyped-defs --allow-untyped-calls --allow-any-generics --check-untyped-defs tools/phase2_aws*.py
python tools/check_docs.py
```

Full final-head Linux CI must additionally pass actual disposable PostgreSQL,
migrations/roles, cancellation/scope/fencing/restart, restricted custody, frontend,
browser, CloudFormation drift/lint, dependency audits, contracts and secret scan.
Skipped tests stay separate from passes; expected baseline failures are not passing
results. Full logs/commands/exit codes/timestamps and source commitments remain
outside Git; final results and CI links are published in the draft PR.

## Preservation and disposition

No registry mutation protocol, immutable root/expiry, lease duration, exact-resource
permission, independent verifier, accepted CR-01..04, SQL/migration 0004,
analyzer/scorer, evaluation contract, custody/watchdog or historical Store changes.
No AWS API, credential, account, spending, real source/custody/export, pilot,
reveal, comparison or scoring. PRs #9/#10 remain draft/unmerged.

**BUDGET NOT PROVEN**: USD $10 remains planning-only until a complete account-specific
quote and failure-liability assessment are independently approved. CR-04 copy
decision remains PENDING. Historical 0/84 and EVAL-ENTRY UNFROZEN are unchanged.
Historical custodian deadlines remain **2026-11-14 17:43:39 UTC** and
**2026-11-16 16:53:29 UTC**; no historical custodian or owner key was accessed.

Disposition: AWS-10-01 correction ready for independent re-review only after all
required checks pass. Cloud deployment and real pilot remain blocked.
