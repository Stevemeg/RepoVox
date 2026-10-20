# Disposable AWS synthetic test proposal

Version: `aws-smoke-plan-1.0`. Date: 2026-10-20. **NOT AUTHORIZED TO EXECUTE.**
[Security contract](aws-retention-integration.md) | [budget inputs](aws-synthetic-test-budget.json) |
[review evidence](../delivery/aws-integration-verification.md).

## Scope, limits and budget decision

Target four active hours, six total hours including cleanup/recovery. One t3.micro,
Standard CPU credits, 8 GiB encrypted boot disk plus 1 GiB encrypted synthetic custody
disk. No GPU, snapshots, created AMIs, Backup, NAT, public IPv4, paid endpoints,
protected S3, owner-key use, real sources, review exports or pilot. Exact quantities
for four bounded Lambdas, schedules, two KMS keys, queues, metadata and logs are in
the budget JSON. Concurrency/timeouts/storage limits are technically enforceable;
six-hour successful deletion, total API count, log bytes, cloud availability and a
$10 bill are not hard quotas. Quotas and budget alarms do not guarantee a ceiling.

Assessment: **BUDGET NOT PROVEN**. Reference-known subtotal is about **$3.0878** plus
a **$2 contingency reserve**, before nine unknown charge categories. This is neither
a quote nor a total estimate. Regional/account EC2 price, DynamoDB transactions,
opaque metadata retained 90 days, KMS RSA requests, logs/CloudTrail, SQS/SNS delivery,
image/bootstrap/networking, taxes/support/operator and outage persistence are
unresolved. Never assume free credits, zero tax, free endpoint connectivity or an
operator contract. The earlier $45.79/month and $10.54/seven-day partial examples
are not the $10 smoke budget and remain incomplete references.

Fresh quotes must cover primary/secondary regions, account setup/support, CPU
credits, all root/custody capacities, baseline IOPS, snapshots/Recycle Bin absence,
Lambda cold starts/retries/GB-seconds, Scheduler attempts, DynamoDB transaction
double costs/storage, S3 versions/requests/Object Lock, RSA-3072 KMS request class,
log ingestion/retention/query, CloudTrail, alerts/HTTPS/SMS, SQS polling, network,
DNS/IPv4/endpoints/egress, taxes/currency and failure persistence. Provider rate
sources are linked in each worksheet row. Published examples are not a regional
offer. Do not prorate retained keys/opaque metadata out of the test liability.

No spend request above **$10 total** is proposed. If total including contingency
cannot be established, recommend a smaller **30-minute control-only SDK/IAM canary**
with no EC2, EBS or protected payloads, separately costed/approved. That smaller
test cannot establish stopped-guest cleanup. Neither option is currently authorized.

## Required approvals and operator arrangement

Before any account/API/credential operation, require all of:

1. Independent review of exact code, IaC, IAM and failure model; approved live wiring
   and settled-write authority, with no wildcard destructive profile.
2. Exact dedicated workload/security accounts, organization, primary/secondary
   regions, data residency, account setup authority and permitted roles.
3. Signed resource/count/duration manifest, selected official Ubuntu AMI ID and
   digest, code/image/package hashes, owner-retained root/receipt and no real data.
4. Account-specific complete quote within $10, tax/contingency/retained-metadata and
   failure-liability decision. A missing quote remains blocking.
5. Named test operator covering the entire scheduled window and unresolved cleanup,
   tested incident endpoint, alternate escalation and explicit outage handover.
   If coverage cannot persist until absence, do not start. No 24/7 service is claimed.
6. Explicit single-use owner deployment/spend authorization for this synthetic test,
   expiry and exact proposed commands. No approval for real evaluation is implied.

Do not use enrolled owner private key for AWS service identity. Future credential
provisioning belongs to the approved operator session, never routine workers or CI.
Account provisioning is optional and separately approved; controllers never receive
Organizations permissions. Reject shared accounts and any historical custody mount.

## Proposed commands, not executed

Offline preparation is safe now:

```powershell
$env:PYTHONPATH='.'
python tools/phase2_aws_infrastructure.py --check
python tools/phase2_aws_budget.py
cfn-lint --template infra/aws-retention/*.template.json
```

The following are **future authenticated AWS calls**, blocked pending all approvals.
Profiles, parameters and paths must be exact owner-approved values, not defaults:

```text
aws sts get-caller-identity --profile APPROVED_PROVISIONER
aws cloudformation validate-template --template-body file://infra/aws-retention/workload.template.json --region APPROVED_REGION
aws accessanalyzer validate-policy --policy-document file://APPROVED_EXACT_POLICY.json --policy-type IDENTITY_POLICY --region APPROVED_REGION
aws iam simulate-principal-policy --policy-source-arn APPROVED_ROLE_ARN --action-names APPROVED_ACTION --resource-arns EXACT_REGISTERED_ARN
aws cloudformation create-change-set --stack-name APPROVED_STACK --change-set-name APPROVED_CHANGE --template-body file://APPROVED_TEMPLATE.json --parameters file://APPROVED_PARAMETERS.json --capabilities CAPABILITY_IAM --region APPROVED_REGION
aws cloudformation describe-change-set --stack-name APPROVED_STACK --change-set-name APPROVED_CHANGE --region APPROVED_REGION
```

Do not execute a change set merely because validation passes. Review exact resources
and IAM plus budget; operation-grant authentication is not a CloudFormation boolean.
No default command here executes/deploys a stack or accesses credentials.

## Future execution and rollback

Record exact operator, UTC clock, account/region/caller role and approved manifest.
Create only empty destinations; record dynamic IDs and receipts durably before
payloads. Compile `binding_template(resources)` from their exact IDs; never install
the synthetic policy's dummy IDs or temporarily use wildcard deletion authority.
Verify permissions with denied wrong-account/region/resource/role canaries and
successful exact canaries. Register root and original fixed expiry, then verify
external expiry/reconcile/secondary routes, DLQ, SNS delivery and write settlement.
Protected activation remains forbidden until that complete evidence passes.

Use synthetic opaque payload <=1 MiB. Test genuine stopped guest, denied API,
attached EBS, cleanup restart, missing heartbeat and independent KMS verification.
Optional S3 version/marker/upload or snapshot/Backup behavior requires an amended
resource manifest/quote; first $10 profile enables none. No imported RepoVox pilot.
End active work at four hours, fence immediately on any failure, do not auto-retry
the attempt. Preserve opaque command/API commitments and failure codes privately.
Leave independent recurrence/alarms active until all registered bytes are verified
absent. If provider APIs are unavailable at six hours, declare OVERDUE, alert and
handover; do not issue COMPLETE or pretend billing stopped.

Rollback cannot be `delete-stack` as proof of cleanup: disks/metadata intentionally
retain, EBS may still be attached, Object Lock/KMS pending deletion have separate
lifetimes. Fence authority first; revoke provisioning/writing and establish settlement.
Terminate exact compute, wait for provider-confirmed terminal state and detached
volumes, delete only registered disks. Inventory every account/region page through
the independently authenticated verifier, including unexpected copies. Unknown
resources block and require owner disposition; do not broaden cleanup grants.

After independent signed absence and repeated reconciliation, record final exact
inventory, count/IDs/commitments, clocks, no protected bytes, nonce and signature.
Then separately authorize teardown of empty metadata/control infrastructure,
Object-Lock version obligations, KMS deletion schedule, log retention, queues,
images, network and accounts. Account closure is not an automatic rollback action.
No host export is allowed. Document every remaining opaque retained destination and
billing liability; never delete unrelated sentinel resources.

## Required live evidence template

For each step record command/SDK method, UTC start/end, exit/status, exact resource
identity, expected/actual deny/allow, opaque response SHA-256, operator and independent
verifier principal. Record creation-intent/registration gaps, revoked/in-flight work,
original expiry, scheduler/monitor progress, alarm delivery acknowledgments, cleanup
failures, each absence page and final signed nonce receipt. Never log source/prediction
bytes, credentials or owner keys. Include actual costs and unresolved liabilities.

Offline tests cannot validate IAM propagation, trust/SCP effectiveness, provider
pagination consistency, XML encoding, KMS policy, EBS attachment/deletion timing,
version/multipart races, scheduler delivery, alarm subscriptions or billing. Those
remain explicit separately approved live acceptance tests. Real custody additionally
needs contracted 24/7 response and approved CR-04 copy controls; a six-hour synthetic
operator does not satisfy those prerequisites.
