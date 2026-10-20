# AWS integration offline verification and reviewer handoff

Date: 2026-10-20. Status: proposed for independent review, not deployed.
Branch: `phase2/aws-retention-integration`, directly stacked on accepted
`6b412e930dfcfd6b771a457d27633f5f7d5ac8e5`. PR #9 remains draft/unmerged;
this additive package has its own draft review request targeting that branch.
The final exact commit, CI run and attribution readback are recorded in that PR.

## Result and entry points

Implemented model-validated AWS SDK adapters, conditional external registry,
independently authenticated/signed absence interface, exact policy compiler,
five disabled CloudFormation stacks and simulated failure/recovery tests.
Start with [ADR-0022](../adr/0022-aws-retention-integration.md),
[security/transaction contract](../operations/aws-retention-integration.md) and
[$10 disposable proposal](../operations/aws-synthetic-test-runbook.md).

No AWS API, account, credential, paid infrastructure, real source or pilot was used.
No owner private key or historical custodian was accessed. No independent acceptance
is claimed. Deployment remains blocked. **BUDGET NOT PROVEN**.

## Changed-file inventory

Implementation:

- `tools/phase2_aws_contract.py`
- `tools/phase2_aws_cleanup.py`
- `tools/phase2_aws_creation.py`
- `tools/phase2_aws_inventory.py`
- `tools/phase2_aws_registry.py`
- `tools/phase2_aws_verifier.py`
- `tools/phase2_aws_operations.py`
- `tools/phase2_aws_infrastructure.py`
- `tools/phase2_aws_budget.py`

Synthetic tests:

- `tests/unit/aws_fixtures.py`
- `tests/unit/test_aws_adapters.py`
- `tests/unit/test_aws_registry.py`
- `tests/unit/test_aws_security.py`
- `tests/unit/test_aws_recovery.py`
- `tests/unit/test_aws_budget_creation.py`

Deterministically generated disabled infrastructure and concrete synthetic policies:

- `infra/aws-retention/accounts.template.json`
- `infra/aws-retention/workload.template.json`
- `infra/aws-retention/security.template.json`
- `infra/aws-retention/secondary.template.json`
- `infra/aws-retention/exact-binding.template.json`
- `infra/aws-retention/cleanup.policy.json`
- `infra/aws-retention/verifier.policy.json`
- `infra/aws-retention/cross-account-trust.policy.json`

Governance and documentation:

- `.github/workflows/phase1.yml`
- `AGENTS.md`
- `docs/adr/README.md`
- `docs/adr/0022-aws-retention-integration.md`
- `docs/operations/aws-retention-integration.md`
- `docs/operations/aws-synthetic-test-runbook.md`
- `docs/operations/aws-synthetic-test-budget.json`
- `docs/operations/deployment.md`
- `docs/operations/cost-model.md`
- `docs/delivery/roadmap.md`
- `docs/delivery/aws-integration-verification.md`

## Verification evidence and limits

Test commands use the locked application environment and explicit synthetic SDK
credentials against Stubber plus an unconditional before-send refusal. The SQLite
fixture evaluates the emitted transaction predicates, serializes claims and persists
intents across recreated registry instances. It is not DynamoDB service isolation.
KMS responses use a disposable RSA fixture key; this tests actual cryptographic
verification and binding, not AWS key policy or service availability. No fixture
signature is an owner approval or a provider-authenticated receipt.

Commands:

```text
python -m pytest tests/unit/test_aws_adapters.py tests/unit/test_aws_registry.py tests/unit/test_aws_security.py tests/unit/test_aws_recovery.py tests/unit/test_aws_budget_creation.py -q
python -m pytest tests/unit -q
ruff check apps/api tests tools/phase1*.py tools/phase2*.py
ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py
mypy
python tools/check_docs.py
PYTHONPATH=. python tools/phase2_aws_infrastructure.py --check
PYTHONPATH=. python tools/phase2_aws_budget.py
cfn-lint --template infra/aws-retention/*.template.json
```

Early implementation runs: 33, then 52, then 60, then 63 new AWS tests passed;
no skipped scenario was counted as passing. CloudFormation 1.52.0 initially caught
an invalid CPU-credit property, nonexistent IAM transaction action and unused
approval parameter. Corrected the property, used transaction member IAM permissions
and included approval commitment in the guard; all five templates then linted with
exit 0 and no warnings. An early documentation check ran before this report existed
and correctly reported its missing link. Initial lint/format issues were corrected.
Two premature local lint launches failed because the separate tool installation
was still running; those were not successful validation runs. Preserve those
diagnostics alongside later results, never substitute reconstructed logs.

Local combined new/accepted cloud regression suite: **216 passed, zero skipped**
(91.89 seconds), before final binding hardening. The final new AWS suite has **64**
cases before final verifier-enrollment hardening, including 19 independent
service/security cases rerun after strengthening cross-account signer separation.
Full Windows unit suite: **743 passed, 39 skipped**, 338 warnings (140.26 seconds).
POSIX skips are not counted as passes. Ruff and formatting (143 files), strict
application mypy (57 files), docs (97 Markdown/613 links/36 JSON), 32 planning tests
and original cost checks passed. The final registry-binding hardening and additional
negative case were followed by **41 affected tests passing** (21.86 seconds). The
full Windows count above precedes that last added case; final Linux CI covers it.
Final self-review additionally pinned verifier role/public-key commitments in the
immutable root rather than permitting challenge callers to choose trust anchors.
Two negative substitution cases and a cross-account service-signing run cover that
hardening; the final AWS suite has 66 cases. This is additive to the accepted model.
Extra AWS script body checks supplement, rather
than weaken, the application's unchanged strict typing scope.

The isolated lint-tool dependency audit found the Windows venv bootstrap pip 23.2.1
had advisories. Upgraded only that disposable tool environment to pinned pip 26.2.0;
its subsequent audit found no known vulnerabilities. CI applies the same tooling
fix and audits it. An initial extended mypy invocation found duplicate package
names; explicit package bases corrected invocation, then explicit RSA type
narrowing corrected its union diagnostics. No application dependency was changed.

Final-head Linux CI results are added to the draft PR after actual execution. The
full workflow remains required: real disposable
PostgreSQL/migrations, tenant/fencing/scope/restart, restricted custody, browser,
frontend, contracts, audits and secret scanning. None is replaced by AWS mocks.

## Safety review and remaining provider tests

Coverage includes wrong account/role/region/resource, wildcard IAM refusal, exact
native S3 IDs, foreign-namespace disks/snapshots, AMI/Backup/Recycle Bin blockers,
pagination failure, permissions/outage errors, attachment races, owner checks,
creation intent/late identity/lost acknowledgment, concurrent claims, stale tokens,
advancing health/expiry immutability, scheduler failure, Lambda restart, unconsumed
nonce on rejection, KMS binding/forgery/freshness and post-COMPLETE reconciliation.
Unknown resources never acquire cleanup permission. No owner-key dependency exists.

Review the explicit blockers before approving a future deployment:

- Independently reviewed live transport/handler composition and authenticated
  readiness/settlement issuer; deployment guards are not owner authentication.
- Effective AWS authorization, cross-account trust, session/permission boundary,
  SCP, KMS key/grant, resource-policy and propagation/credential-revocation tests.
- Real account inventory pagination/ownership, XML encoding, late writes, EBS
  termination/detachment, Recycle Bin/Backup persistence and absence semantics.
- Real scheduler/DLQ/monitor health, secondary-region outage, SNS delivery and
  endpoint/network routing proof. No monitor/responder has been deployed.
- Complete regional quote within $10 including contingency and residual resources;
  current reference subtotal $3.0878 excludes nine unresolved charge categories.
- Named time-limited test operator and unresolved-cleanup handover. Real protected
  custody separately requires contracted 24/7 incident response.
- Actual owner account/region/resource/scope/duration approval and single-use
  deployment/spend authorization. CR-04 reviewer-copy decision stays PENDING.

No deployment parameter, price worksheet or synthetic fixture supplies any of those
external approvals. A smaller 30-minute control-only test is recommended if the
four-hour/six-hour proposal cannot establish total cost; it cannot prove EBS cleanup.

## Preservation and disposition

Accepted analyzer/scorer `711184e82128c7b0a6f3978cfc1cf13975db39ef`, SQL/control plane
`925752b8df38668349b9ef5a45a34cac7d948253`, accepted CR-01..04 code, application DB
migrations, SQLite custody/watchdog, owner-key boundaries and historical Store are
unchanged. No protected source or prediction bytes enter Git or CI. Original
historical host files/custodians were not inspected or rehashed, and no claim of
their independent revalidation is made.

Old deadlines remain **2026-11-14 17:43:39 UTC** and **2026-11-16 16:53:29 UTC**;
owner-managed host cleanup remains separate. Historical 0/84 is unchanged and is
not measured 0% analyzer accuracy. Official EVAL-ENTRY remains UNFROZEN, with no
synthetic count or human review fabricated. No merge, pilot, reveal, scoring,
deployment or Phase 3 occurred.

**AWS INTEGRATION PACKAGE READY FOR INDEPENDENT REVIEW — CLOUD DEPLOYMENT AND
REAL PILOT BLOCKED.** This disposition requires successful final offline/CI checks;
it never grants independent acceptance or proves the $10 budget.
