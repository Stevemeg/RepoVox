# Independent cloud-retention design and synthetic verification

Date: 2026-10-20. Disposition: **DESIGN AND MOCK PROTOCOL READY FOR INDEPENDENT
REVIEW; CLOUD DEPLOYMENT AND REAL PILOT BLOCKED.** This is not independent acceptance
or a claim that cloud retention is operational.

## Baseline and scope

Accepted operational baseline cb1a6ddaa0c299af0009b3f940217d3cf2647ba7 on draft PR #9,
analyzer/scorer 711184e82128c7b0a6f3978cfc1cf13975db39ef and pilot control
925752b8df38668349b9ef5a45a34cac7d948253. Work continues additively on
phase2/retention-runtime-verification. No accepted extraction, scoring, evaluation
schema, Store, lifecycle, SQL or migration file is modified. No dependency or
application DB migration is introduced. Sole contributor remains Stevemeg.

The owner cannot promise continuous personal/laptop availability. This proposal
therefore replaces that proposed operational dependency with independent cloud
automation plus a separately contracted incident service for exceptional failures.
It does not assert that an AWS account, responder or real cleanup system exists.

## Architecture and permissions handoff

[ADR-0021](../adr/0021-independent-cloud-retention.md) and the
[normative design](../operations/cloud-retention-design.md) cover provider choice,
two-account boundaries, registry identity, immutable expiry, admission fencing,
cleanup/reconciliation, full failure matrix, protected-copy inventory, incident
response and all deployment gates. The policy preview uses synthetic account IDs
and exact destructive ARNs; it is deliberately not a complete deployable policy.
No routine worker, public API, reviewer or GitHub workflow gains cloud authority.

The initial profile uses registered encrypted EBS (root/acquisition/custody and
DB/object-store disks too), restricting UID 10002 with existing POSIX protections.
Snapshots/backups/replicas and unmanaged exports are prohibited. Optional S3
versions/uploads/snapshots are exercised only as explicitly registered mock cases.
Object Lock is reserved for opaque metadata, not protected data needing withdrawal.

The cloud adapter, real IAM/trust compilation, actual Lambda/SDK implementations,
deployment configuration and integration of a fresh cloud-retention proof into
existing execution/custody gates remain **proposed future implementation**, not
silently certified by a model. No running VM or guest assertion can authorize them.

## Concrete code and synthetic observations

[Protocol model](../../tools/phase2_cloud_retention_model.py) has no SDK/network,
credential loader, live Lambda entry point, protected source/prediction bytes or
owner-key dependency. REAL mode fails. It uses SQLite transactions for immutable
root checks, persistent fencing, cleanup leases and action-intent recovery, plus
explicit in-memory mock provider state. The separate observer has an independent
read path over the same simulated inventory; this is not independent AWS proof.

[Adversarial tests](../../tests/unit/test_cloud_retention_model.py) cover stopped
guest eligibility, mandatory activation, missing/stale/future runtime and controller
health, immutable expiry after restart, changed root/tenant/scope, SQL metadata
immutability, wrong endpoint/account/resource/region, unknown copy and deletion
refusal, unrelated sentinel preservation, duplicate cleanup and post-completion
drift, scheduler loss followed by reconciliation, partial deletion, crash after
delete before acknowledgment, concurrent cleaner claims, stale claim rejection,
cancellation/admission races, version/multipart/snapshot order, unresolved writers,
retention holds, separate absence verification, no reopening, expiration, corruption,
mock-only dependency, IAM preview safety and unknown-preserving cost calculations.

The mock's complete in-memory inventory, instantaneous quiescence and supplied
logical clock do not prove AWS consistency, real credential revocation, object
pagination, actual durable cloud storage, real IAM or physical deletion. Tests
delete simulated identities only. No real acquisition/evidence or infrastructure
was accessed; this work never starts VMware, Docker Desktop or a cloud runtime.

## Verification commands and evidence

Final focused run: **54 passed**, zero skipped, 4.80 seconds. Local full unit suite:
**581 passed, 39 skipped**, 338 existing FastAPI/Starlette/tree-sitter deprecation
warnings, 25.07 seconds. Windows skips are reported, not treated as POSIX proof.
Earlier 42/45-case runs and 572/576-pass intermediate suites remain in private
evidence; they are not substituted for the final results. Ruff and formatting pass
(123 files), application mypy passes (57 source files), 32 planning-tool unit tests
pass, docs/contracts/cost/corpus/readiness checks pass. Pip-audit reports no known
vulnerabilities; local repovox 0.1.0 is not a PyPI package and is explicitly unaudited.
Final-head Linux CI remains a required separately observed result recorded on the
draft PR. No prior accepted CI is relabeled as proof of these additions.

This task also preserved ordinary tooling diagnostics: the first document read hit
Windows console encoding and was repeated with explicit UTF-8; GitHub CLI was not
on PATH, so the existing authenticated GitHub connector verified account/PR/commit
identity instead. A malformed patch invocation and unmatched-context patch edits
failed without changing accepted files; corrected bounded edits were checked.
These are tooling failures, not successful verification commands or cloud tests.

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_cloud_retention_model.py -q
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
.venv\Scripts\python.exe tools/phase2_cloud_budget.py --hours 730
.venv\Scripts\python.exe tools/phase2_cloud_budget.py --hours 168
```

Exact UTC timestamps, commands, stdout/stderr, exit codes and SHA-256 evidence are
kept outside Git. The original host-only diagnostics/failures are not overwritten.
The existing CI workflow runs Linux units, real disposable PostgreSQL/migrations,
restricted custody, worker/controller/chronology integration, frontend/browser,
audits and secret scanning. It creates no AWS resource and sees no private evidence.
No cloud SDK/IAM test is represented by those application regressions.

## Costs and practical guarantee

Reference subtotal: **USD 45.794481/month** (730 hours), **USD 10.539004 per
illustrative seven-day, three-family pilot** (168 hours). These are arithmetic
estimates of published reference items only. No free tier assumed. Exact region
quote, SNS/incident delivery, logging/CloudTrail/SSM/API/storage details, network,
tax/currency and independently contracted 24/7 response remain unquoted, never zero.
[Inputs](../operations/cloud-retention-costs.json) preserve those nulls and sources;
[calculator](../../tools/phase2_cloud_budget.py) refuses invalid/duplicate inputs
and always returns complete_budget=false/provisioning_authorized=false.

Conditional eventual deletion is achievable when provider APIs, approved permissions
and registered storage are available. Exact-time deletion is not guaranteed during
outage/suspension, and logical provider absence does not attest forensic erasure.
Unknown/held/unavailable resources stay overdue/incomplete. Reconciliation continues
after first invocation and apparent success. The owner's Windows signing key is
needed only for independently authorized review, never cleanup.

## Historical and official boundaries

Neither historical custodian was accessed, mounted, migrated, reactivated or deleted.
The original deadlines remain **2026-11-14 17:43:39 UTC** and
**2026-11-16 16:53:29 UTC**. Historical host copies remain an independent owner
cleanup obligation; this proposal provides no retroactive coverage or deadline
extension. Historical 0/84 is unchanged, not measured 0% analyzer accuracy.
EVAL-ENTRY remains UNFROZEN and no human-reviewed counts are increased.
No owner private-key file is accessed. No real A/B, gold, reveal, scoring or pilot.

## Owner decisions and independent review checklist

1. Independently review the root/intent/fence protocol, IAM boundaries, mock
   limitations and crash/concurrency results. Acceptance cannot be self-awarded.
2. Approve provider, account boundaries, region/residency, original deadlines and
   audit-metadata lifetime. Resolve every source-only reviewer/provider export's
   enforceable retention; uncontrolled copies block the end-to-end guarantee.
3. Obtain and approve a complete quote and a separately contracted 24/7 incident
   service. No responder, SLA or budget approval has been invented.
4. Authorize a tightly capped disposable synthetic cloud deployment and teardown
   inventory, then implement/review real adapters/IAM/IaC. Prove actual role denials,
   stopped EC2 cleanup, EBS/snapshot/Recycle Bin, complete version/multipart
   pagination, revocation races, schedule/DLQ failure, monitor-health alarms and
   independently empty final cloud inventories with synthetic bytes.
5. Only after genuine review and operational activation may the owner separately
   authorize one new real attempt. Existing key enrollment is not that authorization.
   Capture/reference/reveal/comparison remain separately signed/gated operations.

No PR merge, paid provisioning, production deployment, corpus freeze or Phase 3.
