# Independent cloud-retention review corrections

Date: 2026-10-20. Review baseline:
`95aa6d265038f0b111eec91770690ebd2016a363`, independently accepted for design-stage
engineering only. Follow-up on draft PR #9, not deployment or pilot authorization.
Disposition: **OFFLINE CORRECTIONS PREPARED FOR INDEPENDENT RE-REVIEW; AWS AND REAL
PILOT BLOCKED.** Final-head results are recorded on the draft PR and in the private
command evidence; prior design results remain in the [original report](cloud-retention-design-verification.md).

## Changes and reviewer entry points

| Finding | Implementation | Evidence |
| --- | --- | --- |
| CR-01 | Compound native identities; UTF-8 byte bounds and opaque VersionId/UploadId/key preservation | Native punctuation/length/null/Unicode, distinct normalized-looking strings, same ID across keys/buckets/kinds, wrong endpoint and duplicate tests |
| CR-02 | Root-pinned distinct service principals and verifier public key; separate authenticated read-only inventory interface; signed nonce/fence/catalog/time-bound observations | Separate process and provider database, actual read-only write denial, independent remaining-resource detection, wrong credential/principal/account/region, tamper/coverage/expiry/replay and concurrent consumption tests |
| CR-03 | Durable approved-slot creation intent, one-send dispatch, append-only returned-ID registration and cleanup-only discovery | Abrupt subprocess exits around durable mock creation/registration, no uncertain automatic retry, concurrent dispatch, wrong scope/receipt, unresolved/in-flight/ambiguous results and immutable expiry tests |
| CR-04 | Explicit pending owner record; enforceable options/runbook; offline signed-decision evaluator which never authorizes real export | Pending record blocks; fixture signatures/expiry/tenant/destination/contract/copy-class/duplicate/waiver negative controls |

Exact changed files relative to the review baseline:

- `tools/phase2_cloud_retention_model.py`
- `tools/phase2_cloud_registration.py`
- `tools/phase2_cloud_verification.py`
- `tools/phase2_cloud_handoff_policy.py`
- `tests/unit/test_cloud_retention_model.py`
- `tests/unit/test_cloud_retention_corrections.py`
- `docs/operations/cloud-retention-review-contract.md`
- `docs/operations/cloud-reviewer-copy-decision.md`
- `docs/operations/cloud-reviewer-copy-decision.json`
- `docs/operations/cloud-retention-design.md`
- `docs/adr/0021-independent-cloud-retention.md`
- `docs/delivery/cloud-retention-review-corrections.md`
- `AGENTS.md`

The [1.1 contract](../operations/cloud-retention-review-contract.md) states identity,
authentication, atomicity, crash recovery and provider limitations. Model schema
version 1.1 / SQLite user_version 110 explicitly rejects older mock ledgers. No
existing Store, evaluation schema, dependency or application migration is changed.

## Commands, results and evidence

Final focused run: **135 passed, zero skipped**, one existing warning, 14.87 seconds.
Final local full unit suite: **662 passed, 39 skipped**, 338 existing deprecation
warnings, 31.48 seconds. The Windows skips are retained as skips. Earlier 122/127
focused and 655-pass full runs are preserved rather than relabeled final.
Ruff, formatting (127 files), application mypy (57 files), 32 planning-tool tests,
documentation (92 Markdown / 588 links / 35 JSON), all contract/corpus/readiness and
cost checks pass. Pip-audit reports no known vulnerabilities; local `repovox 0.1.0`
is not on PyPI and is explicitly unaudited. Final-head CI is a separately observed
result recorded on the draft PR and in the private consolidated handoff. Initial
lint found formatting/line-length issues; formatting and bounded line splits
corrected them, with the revised Ruff check passing. Patch context mismatches
failed without modifying files and were corrected; no failed cloud/API test is
hidden. No actual AWS test has been run.

A parallel Ruff run reported a cache-write warning while still returning success;
the explicit `--no-cache` rerun passed with empty stderr. No permission or validation
assertion was relaxed.

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_cloud_retention_model.py tests/unit/test_cloud_retention_corrections.py -q
.venv\Scripts\python.exe -m pytest tests/unit -q
.venv\Scripts\ruff.exe check apps/api tests tools/phase1*.py tools/phase2*.py
.venv\Scripts\ruff.exe format --check apps/api tests tools/phase1*.py tools/phase2*.py
.venv\Scripts\mypy.exe
.venv\Scripts\python.exe tools/check_docs.py
.venv\Scripts\python.exe tools/cost_model.py --check
.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -v
.venv\Scripts\python.exe tools/phase1_contracts.py --check
.venv\Scripts\python.exe tools/phase2_contracts.py --check
.venv\Scripts\python.exe tools/phase2_v2_contracts.py --check
.venv\Scripts\python.exe tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json
.venv\Scripts\python.exe -m pip_audit --local
```

Private evidence directory:
`C:\Users\konab\AppData\Local\RepoVox\cloud-retention-corrections-ee801fe721a64648bba86dba0276b454`.
Each recorded command has original stdout/stderr, UTC start/end, exit status,
elapsed duration and SHA-256 commitments. This directory contains synthetic
engineering evidence, not custody/prediction/private-key material. Windows skips
are separate from Linux CI proof. Existing CI also runs disposable PostgreSQL,
restricted custody, worker/controller, source/tenant isolation, frontend/browser,
dependency checks and history secret scanning; none substitutes for AWS testing.

## AWS-specific work and blocking owner decisions

Still required after separate budget/deployment authorization and independent
design review:

1. Actual read-only verifier service, independent credentials/trust and KMS signing,
   authenticated caller/endpoint checks and least-privilege denial tests. Fixture
   Ed25519 keys are not owner credentials or approved cloud trust keys.
2. Real DynamoDB conditional intent/append implementation, immutable external heads,
   late-response settlement, full S3 key/version/upload pagination, exact SDK URL/XML
   round trips, permissions, versions/delete markers, native failure responses and
   interrupted creation-before-registration tests. No exactly-once AWS claim.
3. Disposable real EBS attachment/termination/snapshot/Recycle Bin and S3 multipart/
   version cleanup/absence tests; independently inspect final inventories.
4. Scheduler/DLQ/reconciler/monitor-health/region-outage testing, contracted incident
   response, complete quote and real provisioning/copy cleanup receipts.
5. Owner decision on [reviewer copies](../operations/cloud-reviewer-copy-decision.md),
   actual provider terms/rights, enforceable copy controls and independent deletion
   verification. No current choice, agreement or approved destination exists.
   A separately signed exact handoff grant is additionally required.

Mock quiescence, full fixture enumeration, logical test clocks and a trusted fixture
signer cannot prove provider behavior or administrator-proof storage. Absence is
logical provider absence, not forensic media erasure or a hard deletion-time SLA.
Uncertain/unavailable resources remain INCOMPLETE. No responder or spending approval
has been invented. Reference costs remain an incomplete subtotal; actual service
authentication/KMS/response costs need a complete quote before deployment.

## Compatibility and preservation

Analyzer/scorer `711184e82128c7b0a6f3978cfc1cf13975db39ef`, control plane
`925752b8df38668349b9ef5a45a34cac7d948253`, migration 0004 and accepted custody
runtime are unchanged. No owner private-key file, real protected packet, historical
custodian, VM or shared Docker service was accessed or started for these changes.
Historical deadlines remain **2026-11-14 17:43:39 UTC** and
**2026-11-16 16:53:29 UTC**, including unchanged separate host-copy obligations.
Historical 0/84 remains unchanged and is not measured 0% analyzer accuracy.
Official EVAL-ENTRY remains UNFROZEN with no new human-reviewed counts.

No cloud resources, pilot, acquisition, real A/B, reference authoring, reveal,
comparison, scoring, deployment, merge or Phase 3. Stop for independent re-review.
