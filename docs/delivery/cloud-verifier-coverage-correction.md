# CR-02: complete read-only verifier coverage

Date: 2026-10-20. Review baseline:
`43dbcfa178f0b6ffec1164bb5f051f0619d7e363`. Draft PR #9 remains unmerged.
CR-01/CR-03 are accepted for the offline model; CR-04 is accepted as a fail-closed
pending owner-decision design. This bounded CR-02 correction requires final
independent review. AWS deployment and real pilot execution remain blocked.

## Root cause and correction

The independently authenticated reader filtered by namespace, registered identity
or an S3 bucket parent. It could return an empty signed observation while an
unregistered EBS volume or snapshot with a different namespace remained present.
The requested two regression tests reproduced those omissions against the original
implementation: **2 failed**, 14 deselected, exit 1. This expected failure is
preserved as `reproduced-original-defect`, not relabeled passing.

The corrected fixed read scope is `DEDICATED_ACCOUNT_REGION`: all present resources
of the six supported kinds in the exact account/region must be enumerated, regardless
of namespace, tenant, tags, registration or parent links. Provider rows outside the
authenticated endpoint boundary and unsupported kinds refuse verification. This
also conservatively includes transitive/disconnected descendants and snapshot copies
with unusable source-volume identity. A remaining unrelated resource blocks an
empty-account receipt; it is never automatically registered, adopted or deleted.

The [normative contract](../operations/cloud-retention-review-contract.md) identifies
compute/volume/snapshot/restored-volume/copy and S3 relationships, distinguishes
account-wide from parent-scoped enumeration and documents limitations. The mock's
single-parent schema is not presented as a complete AWS lineage graph. Parent-only
queries are not accepted as account-wide absence proof. No shared-account, global
all-services, multi-region or provider-level cleanup guarantee is claimed.

`absence-query-1.2` and `synthetic-cleanup-receipt-1.2` explicitly bind and record
the read scope. Legacy/narrower queries fail closed. Existing independent signing,
nonce consumption, freshness, fence/catalog/root binding and real-mode refusal are
preserved. Immutable model 1.1 / SQLite version 110, original expiry and registry
remain unchanged. **Exact-resource cleanup code is unchanged.**

## Exact changed files

- `tools/phase2_cloud_verification.py`
- `tests/unit/test_cloud_verifier_coverage.py`
- `tests/unit/test_cloud_retention_model.py`
- `docs/operations/cloud-retention-review-contract.md`
- `docs/operations/cloud-retention-design.md`
- `docs/adr/0021-independent-cloud-retention.md`
- `docs/delivery/cloud-verifier-coverage-correction.md`
- `AGENTS.md`

## Regression evidence

New tests cover foreign-namespace snapshot and volume omissions, transitive
volume/snapshot state, disconnected resources across all six supported kinds,
unrelated-resource cleanup denial, wrong account/region rows, unsupported kinds,
legacy/narrowed scope refusal and explicit signed scoped receipts. Failed absence
checks leave the nonce unconsumed, state VERIFYING, original expiry/root unchanged.
The earlier sentinel test now requires absence refusal while preserving the sentinel
and exact-delete denial; it no longer endorses false COMPLETE.

Final focused run: **153 passed**, zero skipped, one existing warning, 22.68 seconds.
Local full unit suite: **680 passed, 39 skipped**, 338 existing warnings, 42.88 seconds.
Ruff, formatting (128 files), application mypy (57 files) and docs (93 Markdown,
591 local links, 35 JSON) pass. The earlier 151-pass focused run remains preserved.
Final-head Linux CI is a separately observed result recorded on PR #9 and in the
consolidated command evidence. Skips are never counted as passing.

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_cloud_retention_model.py tests/unit/test_cloud_retention_corrections.py tests/unit/test_cloud_verifier_coverage.py -q
.venv\Scripts\python.exe -m pytest tests/unit -q
.venv\Scripts\ruff.exe check --no-cache apps/api tests tools/phase1*.py tools/phase2*.py
.venv\Scripts\ruff.exe format --check apps/api tests tools/phase1*.py tools/phase2*.py
.venv\Scripts\mypy.exe
.venv\Scripts\python.exe tools/check_docs.py
```

Private original commands/stdout/stderr/exit status/UTC times/SHA-256 evidence:
`C:\Users\konab\AppData\Local\RepoVox\cloud-verifier-coverage-7a6f345486ba4da9a791f551a124f8d0`.
Existing Linux CI additionally runs real disposable PostgreSQL/migrations,
restricted custody, controller/worker, tenant/source isolation, contracts,
frontend/browser, dependency audits and secret scanning. No AWS resource is used.

## Boundaries and remaining work

Future AWS verification still needs independently authenticated complete API
pagination, actual account/region ownership, all attachment/origin fields, S3
bucket-region and version/delete-marker/upload discovery, permission-error handling,
settled writes and provider-native deletion/absence tests. An account-wide metadata
read is a separate permission from exact-resource cleanup. Unknown protected copies
or incomplete provider visibility remain blockers; never infer their absence from
tags, missing relationships, an empty first page or a cleaner's success.

No analyzer/scorer, control-plane SQL, migration 0004, accepted historical Store,
custody runtime, dynamic registration, pending owner-copy decision or dependencies
change. No owner private-key access, real custody/source/export/prediction/reference,
AWS/spending, pilot, reveal, scoring, merge or Phase 3. Historical evidence and
0/84 remain unchanged; that result is not measured 0% analyzer accuracy. EVAL-ENTRY
remains UNFROZEN. Both historical deadlines remain 2026-11-14 17:43:39 UTC and
2026-11-16 16:53:29 UTC, including separate owner host-copy cleanup obligations.

Disposition: **CR-02 OFFLINE COVERAGE CORRECTION READY FOR INDEPENDENT REVIEW**,
conditional on final verification. No independent acceptance is self-awarded.
