# AWS control-only canary independent-review handoff

Date: 2026-10-20. Baseline `e014abd6ec6d397d8bb666188e8c84d9f7525140`
accepted by the owner-reported independent offline review. This additive proposal
continues `phase2/aws-retention-integration`, draft PR #10, on unchanged draft PR
#9 (`6b412e930dfcfd6b771a457d27633f5f7d5ac8e5`). Final head and CI are published
in PR #10; this document does not self-certify independent acceptance.

## What is prepared

The [normative preflight/runbook](../operations/aws-control-canary-preflight.md)
defines one 30-minute **IAM_STS_ONLY** proposal. Four temporary roles/four inline
policies, two stacks, two pre-existing member accounts and a separate existing
Organizations management account. Primary us-east-1; us-west-2 is only a regional
STS denial target with zero deployed resources. No EC2, EBS, KMS, DynamoDB, Lambda,
storage or protected evidence. No account, organization, SCP or existing audit
configuration changes. Only synthetic non-sensitive metadata.

The [cost worksheet](../operations/aws-control-canary-costs.json) contains every
known and unresolved cost category and public reference links. Known additional
service-charge subtotal **$0**; account-specific tax/operator/audit/network/failure
total and residual liability **unknown**. **BUDGET NOT PROVEN**. The previous $45.79,
$10.54 and four-hour reference subtotals are not this canary's budget. $10 remains
planning-only, including all fees, cleanup and contingency.

The [owner form](../operations/aws-control-canary-approval.json) has null account,
operator, quote and authentic approval fields and false authorization flags. No
approved identity, signature, quote, budget, endpoint or live test is fabricated.
All four role trusts/permissions have original time bounds; roles have only exact
read/AssumeRole targets plus explicitly justified read-only ListRoles. Separate
existing read-only identities must remain available for post-teardown verification.

## Exact changed-file inventory

1. `tools/phase2_aws_canary.py`: local disabled-template compiler, proposed-binding
   validation and deterministic descriptive request plan; no SDK/client factory.
2. `tests/unit/test_aws_canary_preflight.py`: offline proposal/policy/budget/disabled
   boundary tests; not real IAM evaluation.
3. `infra/aws-retention/canary-security.template.json`: generated disabled two-role
   security template, exact external operators and cross-account destinations.
4. `infra/aws-retention/canary-workload.template.json`: generated disabled two-role
   workload template, exact cross-account trust and narrowly scoped reads.
5. `docs/operations/aws-control-canary-preflight.md`: resource inventory, trust,
   missing wiring, change-set review, proposed commands, monitoring/teardown,
   independent verification, pricing and limits.
6. `docs/operations/aws-control-canary-approval.json`: pending single-use envelope.
7. `docs/operations/aws-control-canary-costs.json`: regional cost inputs/unknowns.
8. `docs/operations/cost-model.md`: cross-link to the distinct smaller profile.
9. `docs/delivery/aws-control-canary-preflight.md`: this evidence/handoff.

## Deployment limitations requiring review

The current package is **not a deployable end-to-end canary**. No accepted SDK
network refusal or retention handler was removed. A future narrow live runner
still requires separate review/activation: explicit regional endpoints and
federated credentials, authentic approval/single-use enforcement, durable creation
receipt recovery, exact RoleId/account checks, processed change-set comparisons,
memory-only session handling, fixed-clock/request bounds, sanitized evidence and
independent paginated absence. Neither the canary compiler nor a CloudFormation
condition authenticates approval. Descriptive requests are not executable API
arguments. No one can deploy a functioning retention service by flipping a flag.

The initial canary can establish only real trust/read/denial and IAM inventory
behavior, once authorized/wired. KMS signatures/DDB conditions and EC2/EBS/expiry/
unattended custody remain untested and excluded. Independently authenticated IAM
reads are not KMS-signed absence receipts or proof of all-service erasure.

## Verification evidence

All tests here are offline. New cases check disabled role-only artifacts, exact
trust and time bounds, no destructive wildcard permission, mismatched account,
region, namespace, principal and deadline refusals, prohibited resource expansion,
deterministic binding commitments, empty owner approval and unknown budget totals.
The existing botocore before-send refusal and all accepted AWS/cloud regressions
are retained. No live SDK/client construction was introduced into the compiler.

Commands retained outside Git with stdout/stderr, exit codes and UTC timestamps:

```text
python tools/phase2_aws_canary.py --write
python tools/phase2_aws_canary.py --check
pytest tests/unit/test_aws_canary_preflight.py -q
pytest tests/unit/test_aws_adapters.py tests/unit/test_aws_registry.py tests/unit/test_aws_security.py tests/unit/test_aws_recovery.py tests/unit/test_aws_budget_creation.py tests/unit/test_aws_canary_preflight.py tests/unit/test_cloud_retention_model.py tests/unit/test_cloud_retention_corrections.py tests/unit/test_cloud_verifier_coverage.py -q
pytest tests/unit -q
ruff check apps/api tests tools/phase1*.py tools/phase2*.py
ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py
mypy
mypy --explicit-package-bases --follow-imports silent --ignore-missing-imports --allow-untyped-defs --allow-untyped-calls --allow-any-generics --check-untyped-defs tools/phase2_aws*.py
python tools/check_docs.py
```

Local verification: **25 new tests passed** (0.45 seconds); **251 focused AWS/cloud
tests passed** (40.19 seconds), both with one warning and no skips. Full Windows
units: **778 passed, 39 skipped, 338 warnings** (62.24 seconds). Ruff/format (145
files), strict application mypy (57 files), AWS body checks (10 files), template
drift and documentation (100 Markdown/626 links/38 JSON) passed. Windows POSIX
skips are not counted as passes. Final Linux results are recorded in the draft PR
after verification.
Initial Ruff reported long source lines during authoring; formatting and a shorter
assertion description corrected them, without changing a gate. They are not
reported as passing initial lint. Full final-head Linux CI also checks native
CloudFormation artifacts, dependency/secret audits, frontend/browser and disposable
PostgreSQL/restricted custody compatibility. Skips/cancellations remain separate.
No existing failed engineering evidence is overwritten.

## Independent review and owner decisions

Review exact role permissions/trust/time semantics, IAM global versus STS regional
behavior, read-only inventory breadth versus exact deletion, trusted provisioning
boundary, setup/cleanup failure handling, residual metadata and unknown charges.
Verify all current deployment refusals remain, and no proposed credential-bearing
CLI command could leak secrets into transcripts. Confirm live runner incompleteness
is explicit and cost subtotal is never represented as a total budget.

Owner still supplies exact accounts/organization/regions, existing effective roles
and policies, account audit/security cost configuration, complete quote including
operator/tax/residual liability, actually available primary/backup/verifier,
evidence destination, original fixed deadlines and a single-use authentic approval
of final code/templates/operation envelope. Provider-assigned IDs are appended only
after real authorized creation; changes outside the approved envelope stop work.
No owner private-key use is requested by this preflight.

## Preservation and disposition

No accepted AWS cleanup/registry/verifier/SDK, analyzer/scorer, SQL/migration 0004,
custody/watchdog or historical Store changes. No AWS API (including STS, validation
or pricing API), credentials, owner-key access, infrastructure, cost, real source,
custody, reviewer export, A/B, reveal, scoring, merge, deployment or Phase 3.
Public AWS documentation/pricing web pages were consulted as references only.

CR-04 remains PENDING OWNER DECISION. Historical 0/84 is unchanged and is not a
measured 0% analyzer accuracy. EVAL-ENTRY remains UNFROZEN. Historical custodian
contents were not accessed or independently rehashed: preservation evidence here
is the bounded changed-file/commit audit, not an invented custody inspection.
Original deadlines remain **2026-11-14 17:43:39 UTC** and **2026-11-16 16:53:29 UTC**;
host-side cleanup is separately owner-managed. Both PRs remain draft and unmerged.

**AWS CONTROL-ONLY CANARY PREFLIGHT READY FOR INDEPENDENT REVIEW — NO SPENDING OR
DEPLOYMENT AUTHORIZED.** Budget disposition: **BUDGET NOT PROVEN**.
