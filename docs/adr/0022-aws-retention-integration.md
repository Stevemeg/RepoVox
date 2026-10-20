# ADR-0022: Deployment-disabled AWS integration and independent service proof

Status: Proposed for independent review. Date: 2026-10-20.

## Context and decision

The owner accepted CR-01 through CR-04 for offline engineering at
`6b412e930dfcfd6b771a457d27633f5f7d5ac8e5`. Actual provider request adapters,
conditional registry operations and IAM templates were still missing. Add these
in separate modules; leave the accepted offline model and all application,
custody, owner-key and SQL implementations unchanged.

Use injected SDK clients with an unconditional before-send network refusal.
No ambient client/credential construction, AWS CLI invocation, owner-key access
or deployment command is implemented. CloudFormation resources all require a
false-by-default deployment condition. Schedules are additionally disabled and
Lambda activation refuses. These layers prevent accidental activation; they are
not authentication of a future owner approval and do not replace live IAM tests.

Dedicated workload account discovery is deliberately broad and read-only.
Exact native registered identities alone compile destructive grants. AMIs,
backups, Recycle Bin rules/items, unexpected disks and unsupported S3 profiles
block absence proof. Do not adopt unknown resources or infer copy lineage.

Keep the verifier in a separate role/Lambda with a service-managed RSA-3072 KMS
signing key. Its observations bind nonce, root, generation, registration revision,
scope, timestamp and complete coverage. Pinned public DER hashes and durable
conditional nonce consumption prevent substitution/replay. This is an additive
AWS interface, not a reinterpretation of accepted Ed25519 offline observations.
The Windows owner's independent review signatures remain unchanged.

## Consequences and limits

Provider creation and DynamoDB cannot form one atomic transaction. Commit intent
before dispatch, register native result before acknowledgment, never automatically
repeat uncertain creation, and forbid COMPLETE until independently established
write settlement and signed empty discovery. Revocation and termination cannot
prove immediate quiescence; the live settlement authority is an explicit blocker.

The $10 ceiling supersedes the former $25 planning figure. A four-hour/six-hour
synthetic smoke plan is prepared, but total cost is **BUDGET NOT PROVEN**. There is
no hard billing ceiling or bounded outage-persistence liability. No deployment or
real pilot is authorized, and no cloud behavior/IAM acceptance follows from mocks.

See the [integration/security contract](../operations/aws-retention-integration.md),
[disposable runbook](../operations/aws-synthetic-test-runbook.md),
[cost worksheet](../operations/aws-synthetic-test-budget.json) and
[review evidence](../delivery/aws-integration-verification.md).
