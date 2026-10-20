# Disposable AWS control-only canary preflight

Version `aws-control-canary-preflight-1.0`; 2026-10-20. **Proposal only. No AWS API,
credentials, deployment or spending authorized.** Accepted offline baseline:
`e014abd6ec6d397d8bb666188e8c84d9f7525140`, draft PR #10 stacked on unchanged
draft PR #9. Independent acceptance of that package does not accept cloud operation.

[Approval form](aws-control-canary-approval.json) |
[Cost worksheet](aws-control-canary-costs.json) |
[Verification/handoff](../delivery/aws-control-canary-preflight.md) |
[Broader accepted integration](aws-retention-integration.md).

## Recommended scope and feasibility

Recommend **IAM_STS_ONLY**, 30 minutes from a fixed UTC start, then a 30-minute
teardown reserve and a named 24-hour follow-up obligation. No renewal, second
execution or automatic retry. The two new templates create only four IAM roles
with four inline policies. CloudFormation contributes two stack records.
Use at most 100 application probe requests; pagination, CloudFormation/provider
internal retries and teardown calls are accounted separately and are not a hard
provider API-count cap. Record their actual quantities. SDK retries in a future
runner must be disabled; intentional one-shot negative probes are not failed-test
retries. Unexpected errors stop probes and start exact-resource teardown.

This can test real regional STS trust, identity checks, narrowly allowed IAM reads,
negative authorization and independently authenticated IAM inventory. It cannot
test KMS signing, DynamoDB transactions, deployed retention Lambdas, external
scheduling, signed cloud-absence receipts, EC2/EBS cleanup, retention enforcement,
VM-off recovery, protected custody or 24/7 response. KMS/DynamoDB are **excluded**,
not optional switches in this approval. Adding either needs a revised resource,
policy, cost and authorization envelope. The existing larger four-hour plan is
unchanged; its budget does not apply to this smaller test.

The proposed AWS operations are technically feasible. The current package has an
offline plan compiler, disabled templates and refusing AWS adapters, **not a
deployable end-to-end canary runner**. Changing DeploymentAuthorized is insufficient.
Do not activate the broader blocked Lambda handlers for this test.

## Accounts, regions and prerequisites

Require two separate, dedicated, pre-existing member accounts: workload and
security. Require a separately administered pre-existing Organizations management
account and an owner-approved organization ID: **three existing accounts total;
zero accounts/organizations/OUs/SCPs created or modified by this canary**. If these
do not exist, their setup needs a separately reviewed account/billing decision;
it cannot be silently included in $10. Management never runs probes or cleanup.
Disclose all SCPs, boundaries, session/resource policies, installed CloudFormation
hooks, delegated administrators and inherited audit/security automations.

Propose primary **us-east-1 (N. Virginia)** for both stacks and regional STS;
secondary **us-west-2 (Oregon)** solely for one regional STS denial probe. These
match the package's existing example regions, avoid an opt-in-region prerequisite
and provide distinct regional endpoints. Owner residency, service availability,
billing and organization constraints must confirm this choice. No resources or
secondary observer are deployed in Oregon. This is not multi-region monitoring.

IAM resources are global. A requested-region denial on regional STS is not proof
that IAM is regional or all AWS services are region-restricted. Use explicit
regional STS endpoints; reject the global endpoint in the future runner. AWS
documents the [global endpoint's us-east-1 condition-key behavior](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_region-endpoints.html).
GetCallerIdentity is identity evidence, not a permission test: it
[needs no permission, even with an explicit deny](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html).
Require successful and denied calls on the same authenticated session and exact
live RoleId readback, not only a plausible ARN or an IAM simulator prediction.

## Exact proposed resource and copy inventory

`N` means a new owner-approved 16-character lowercase hex namespace, never an
existing resource. Account IDs and existing principal ARNs remain null in the form.
No synthetic example account is a real approval.

| Account / region | Exact proposed identity | Count | Purpose and cleanup |
| --- | --- | --- | --- |
| Security / IAM global | `rv-canary-N-Caller` | 1 role | Trust only approved OperatorRoleArn; self GetRole and AssumeRole of exact workload Probe |
| Security / IAM global | `rv-canary-N-Verifier` | 1 role | Trust only separate VerifierOperatorRoleArn; IAM reads on these two roles, ListRoles, and exact workload Audit assumption |
| Workload / IAM global | `rv-canary-N-Probe` | 1 role | Trust exact security Caller; GetRole on itself only |
| Workload / IAM global | `rv-canary-N-Audit` | 1 role | Trust exact security Verifier; GetRole/GetRolePolicy/ListRolePolicies/ListAttachedRolePolicies on these two roles and ListRoles |
| Each role | inline policy `CanaryOnly` bound to exact role ARN | 4 policies | No managed-policy attachments; delete inline policy before DeleteRole if manual recovery is needed |
| Security / us-east-1 | stack `rv-canary-N-security`, change set `rv-canary-N-create` | 1 stack / 1 change set | Register returned stack/change-set ARN and RoleId before acknowledging provision; remove unexecuted change sets and stack |
| Workload / us-east-1 | stack `rv-canary-N-workload`, change set `rv-canary-N-create` | 1 stack / 1 change set | Same; independently verify IAM absence, not only stack status |
| Both regions / both accounts | EC2, EBS, snapshots, AMIs, KMS, DynamoDB, S3, Lambda, Scheduler, SNS/SQS, custom metrics/alarms/log groups, networking | **0** | Prohibited; cannot be added during execution |
| Existing owner-approved audit systems | Exact destination inventory supplied before approval | 0 new | May receive synthetic control-plane metadata automatically; quote costs and record existing retention, including replicas/versions/backups |
| Approved operator evidence location | Exact non-Git path supplied before approval | 1 bounded evidence inventory | Synthetic IDs, commitments, request IDs and sanitized results only; explicit retention/deletion owner and due date |

Templates: `infra/aws-retention/canary-security.template.json` and
`infra/aws-retention/canary-workload.template.json`. No custom resource, macro,
nested stack, account reservation, role credential, source or protected byte.
CloudFormation may retain deleted-stack metadata; CloudTrail event history also
survives. Do not promise erasure of AWS control-plane history. Only synthetic,
owner-approved non-sensitive identifiers may enter it. Application evidence must
never include STS AccessKeyId, SecretAccessKey, SessionToken or signed requests.

Create a durable local synthetic-only intention before each provisioning call;
record exact returned IDs before acknowledgment. Lost create acknowledgment stops
execution: discover only the approved exact stack/role names and compare template,
creation time and RoleId. Zero/multiple/conflicting candidates are INCOMPLETE;
never issue a replacement create or adopt a similarly named resource. A before
inventory must show no pre-existing role/stack with the proposed names. Trust
relationships use exact principal ARNs, not tags; read back principal IDs to detect
role replacement. An unrelated role's presence is not deletion authority.

## IAM and authentication contract

All four role trusts require exact Principal, ExternalId, PrincipalOrgID,
RequestedRegion=us-east-1 and fixed NotBeforeUtc <= CurrentTime < NotAfterUtc.
Every inline permission has the same time window; requested sessions are 900
seconds. IAM's role maximum is set to 3600 seconds, not misleadingly claimed to
enforce a 30-minute role maximum. A last-minute session can outlive the test window,
so the permission time condition is necessary. IAM propagation is eventual:
no instantaneous session-revocation claim. Record any delayed denial as a failure.

The Caller can assume only the exact Probe. Verifier can assume only Audit.
Probe can only read itself. Audit/Verifier can read policy attachments and bodies
for their two exact account roles; their only Resource `*` permission is
`iam:ListRoles`, because account inventory cannot be ARN-scoped. Listing never
grants mutation. Test identities get no provisioning, deletion, PassRole, KMS,
DynamoDB, cloud-retention, owner-key, SQL or custody privilege.

Pre-existing **operator**, **verifier**, **provisioner/teardown** and
**post-teardown read-only verifier** identities are external prerequisites; record
their exact ARNs, session issuers, effective policies and account association.
Verifier credentials/control must be distinct from the probe/provisioner, including
a separately controlled existing read-only identity in **each** account that stays
usable after the four temporary roles are removed. No access keys are created.
Use short-lived federation and approved local credential isolation, never keys in
Git, logs, argv, environment dumps or test artifacts. Do not use the owner Ed25519
key, even for service authentication. No KMS/service signing permission is granted.

Proposed provisioning permissions, held only by separately approved existing
operators, are CloudFormation Create/Describe/GetTemplate/GetTemplateSummary/
Execute/DeleteChangeSet, DescribeStackEvents/Resources, ListStackResources,
DescribeStacks and DeleteStack on the two exact approved stack/change-set
identities in each correct account/region. Before returned ARN allocation,
CloudFormation's generated stack/change-set suffix requires a narrowly bounded
`rv-canary-N-.../*` ARN pattern; replace with exact returned ARNs before execution
where IAM supports it. Discovery ListStacks/ListChangeSets/GetTemplateSummary may
need separate read-only `*` scope; justify against the current AWS action table.
Do not claim universal ARN support for every API. Record this as an effective-IAM
test prerequisite rather than guessing a broad deploy policy.

Native role provisioning needs `iam:CreateRole`, `GetRole`, `DeleteRole`,
`PutRolePolicy`, `GetRolePolicy`, `DeleteRolePolicy`, `ListRolePolicies`,
`ListAttachedRolePolicies` on only the two exact role ARNs per account. No managed
policies, instance profiles, PassRole or trust-update authority are requested;
if the provider requires additional operations, STOP and review, never widen
permissions automatically. IAM cannot restrict arbitrary policy bodies merely
using a target ARN. The provisioning operator is a trusted, separately reviewed
boundary, with approved templates and no unreviewed changes. Existing IAM/SCP
permissions must be independently checked. Do not grant AdministratorAccess to
make this work. The templates create no CloudFormation service role; use the
approved provisioning session directly and reject a supplied RoleARN.

Offline tests inspect policy structure and planned bindings. They do not prove
effective AWS permission evaluation. [Policy simulation has limitations](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html);
no paid Access Analyzer custom/unused-access analysis is included. No SCP or key
policy changes are authorized by this package.

## Missing deployment wiring and offline entry points

`tools/phase2_aws_canary.py` compiles local disabled templates and a deterministic
request **plan** from a validated proposed binding. It imports no SDK, constructs
no credentials and exposes no deploy switch. All live-mode refusal in the accepted
SDK and retention handlers remains unchanged. Run locally only:

```text
PYTHONPATH=. python tools/phase2_aws_canary.py --check
pytest tests/unit/test_aws_canary_preflight.py -q
```

Before a real canary, the following needs separate independent engineering review
and owner activation authorization: a minimal explicit-endpoint live transport;
actual federated identity and effective-policy attestation; signed/otherwise
authentic owner approval validation and durable single-use consumption; resource
intents/returned-identity receipt storage; exact processed change-set validation;
memory-only AssumeRole credential handling; request/deadline limits; refusal of
wrong RoleId/account/region; independent paginated IAM inventory; sanitized evidence
capture and exact teardown with independent error/absence classification.
No such live client factory, permission attestations or full runner is claimed here.
The existing blocked cleanup handlers and settlement issuer are unrelated and
remain blocked. Account-specific wiring cannot be fabricated from null inputs.

## Change-set review and proposed future commands

**Do not execute these commands now.** Every AWS CLI command below needs separate
API/deployment authorization, even get-caller-identity or validate-template. Do not
copy dummy account IDs. Store approved binding/parameters outside Git; no secrets
or STS credential outputs in command transcripts. Confirm CLI binary/version,
endpoint, region, account, assumed principal and profile independently before use.

1. Pin engineering SHA and both template SHA-256s. Review the filled approval,
   full cost quote, existing account inventory and trust/SCP evidence. Consume the
   one-use authorization durably before any authorized create. A failed attempt
   is not reusable. No organization/account creation or broad retention deployment.
2. Use approved external provisioner to inspect both accounts read-only. Confirm
   exact names absent, quotas adequate, regional STS enabled, no unexpected hook,
   StackSet or security automation. No subscription/trail/Config changes.
3. Create **security first**, since workload trust pins the security roles, which
   must already exist. IAM policies may name not-yet-created workload ARNs. Review
   and execute security, then the workload change set. Do not retry failed creates.
4. For each CREATE change set, use inline TemplateBody (no S3 upload), only reviewed
   parameters and CAPABILITY_NAMED_IAM. No RoleARN, transforms, nested stacks,
   imports, third-party types, retained resources or automatic update. Request
   OnStackFailure=DELETE. Do not combine ResourceTypes and Capabilities (API permits
   only one); independently check the complete processed resource list.
5. Describe every change/page and processed template. Require exactly Add of the
   two expected AWS::IAM::Role resources, exact trust, policy, time, account/region,
   namespace and deletion behavior. Review any HookInvocationCount and stop on
   unapproved hooks. Hash/store the complete plan and actual ARNs. Never assume
   change-set success proves permissions or later creation success.
6. Independent reviewer/operator acknowledges exact hash match inside the original
   owner-approved envelope before ExecuteChangeSet. Any difference stops; no
   silent resubmission, permission widening or owner-approval substitution.

```powershell
# FUTURE ONLY; $... variables must come from the separately approved binding.
aws sts get-caller-identity --profile $ApprovedProvisioner --region us-east-1
aws cloudformation create-change-set --profile $ApprovedProvisioner --region us-east-1 --stack-name $ExactStack --change-set-name $ExactChangeSet --change-set-type CREATE --template-body file://$PinnedTemplate --parameters file://$ApprovedParameters --capabilities CAPABILITY_NAMED_IAM --on-stack-failure DELETE
aws cloudformation describe-change-set --profile $ApprovedProvisioner --region us-east-1 --change-set-name $ExactReturnedChangeSetArn --include-property-values
aws cloudformation get-template --profile $ApprovedProvisioner --region us-east-1 --change-set-name $ExactReturnedChangeSetArn --template-stage Processed
# Only after exact independent review under the original approved envelope:
aws cloudformation execute-change-set --profile $ApprovedProvisioner --region us-east-1 --change-set-name $ExactReturnedChangeSetArn
```

The [CloudFormation change-set API](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_CreateChangeSet.html)
defines failure behavior and parameter restrictions. Review the
[IAM escalation implications](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/control-access-with-iam.html).
Creating an unexecuted change set is still an external control-plane change and
is not authorized now. Do not run `aws sts assume-role` with default output: it
prints credentials. Future probe credential transfer must remain entirely in
process memory through the separately reviewed runner.

## Probe, monitoring and failure policy

Before T0, both stacks, RoleIds and effective policies must match. If provisioning
does not finish inside the approved setup window, do not move T0/expiry; cancel
probes and clean up. Only the owner can authorize a different future attempt.

At T0 authenticate the caller, obtain one 900-second Probe session through the
approved Caller, and read its exact GetRole/RoleId. In distinct sessions test wrong
ExternalId, wrong principal, secondary-regional AssumeRole and Probe reading the
existing unapproved Audit role: require AWS AccessDenied, not network failure,
missing resource, timeout or arbitrary error. Independent verifier uses its own
Verifier -> Audit path, checks exact policies and complete IAM inventory. A separate
wrong-account fixture/receipt must be rejected by the runner before action; this
does not authorize probing another unapproved AWS account.

To prove time denial rather than credential expiry, obtain a 900-second session
near the end of the active window; after NotAfterUtc attempt the same allowed read
while the session itself would still be valid. Require AccessDenied. Do not change
the deadline, extend a session or re-assume after expiry. Tests of mutation denial
must not issue potentially destructive writes to real/unrelated resources; rely
on approved safe read/trust negatives and effective-policy inspection for this
initial profile. Dangerous write-denial canaries are outside scope.

Named primary operator observes progress and UTC clock **every minute** during
setup/probes/teardown; independent verifier checks at start, after provisioning,
at deadline, after teardown and follow-up. Named backup cleanup operator must be
reachable for the entire window and any unresolved failure. Have a tested contact
channel outside the test process plus externally visible deadline reminders at
T-5, T0, T+25, T+30 and teardown deadline. Record actual acknowledgment; a reminder
or running process is not an operator contract. Both operators need access not
dependent on a single laptop. The owner has not supplied these arrangements.

Stop probes immediately on identity mismatch, clock skew, missing operator,
unexpected resource, incomplete inventory, permission failure, timeout or
unapproved charge. Disable new admissions in the future runner's durable one-use
record, preserve sanitized reason/request IDs and perform only original exact
teardown. IAM time conditions do not guarantee that role objects disappear.
No human/probe liveness arrangement here qualifies for real protected custody.

## Teardown, independent absence and residual liabilities

Remove the workload stack first, then security. Prefer CloudFormation DeleteStack
with the exact returned stack ID; poll errors to a fixed deadline. Delete any
unexecuted change sets, check stack events and independently inspect all four
RoleIds/ARNs. If stack deletion fails, the approved cleanup operator may remove
only the four registered inline policies/roles after rechecking exact RoleId,
creation receipt and absence of unexpected attachments. An unexpected managed
policy, instance profile or replacement RoleId escalates; do not detach/delete it
using a wildcard or automatically acquire broader authority. No unrelated cleanup.

The independent **pre-existing** read-only principals, not the roles being
deleted, perform complete paginated ListRoles in both accounts and exact GetRole
lookups. Check expected RoleIds against the before/created inventories and inspect
attachments/change sets/stack residuals; identify unexpected creations without
granting deletion authority. NoSuchEntity on exact IAM reads plus complete lists
is absence evidence; AccessDenied, missing page, throttling or network failure is
INCOMPLETE. Compare RoleIds as well as names to detect delete/recreate substitution.
Repeated late checks are needed for IAM eventual consistency, within fixed limits,
without rerunning the actual test. Failures remain unresolved and escalate.

Use a new one-use verifier nonce bound to approved manifest/template hashes,
accounts/regions, recorded RoleIds, observation time and independent principal
identity. Capture sanitized AWS request IDs and original read-only responses.
This is independently authenticated inventory evidence **not** the accepted
KMS-signed retention absence protocol: no service key is created. An operator's
local digest does not cryptographically authenticate AWS or prove all-service
absence. For higher assurance, use separately retrieved CloudTrail metadata where
available; absence of an event is not proof of no operation. Do not claim real
signed verification is tested. Preserve pending KMS verification as excluded.

Record `REQUESTED`, `INCOMPLETE` or `ABSENCE_OBSERVED` per registered resource.
Only independently observed absence permits canary teardown completion; API success,
DeleteStack success alone, pending operations or a running monitor do not. Account
inventory must show no unexpected resource attributable to the test. Known audit
history/stack metadata is explicitly retained metadata, not a false all-resources
absent claim. Record exact destination/retention, remaining expenses and operator
obligations. Follow up through T+24h and bill availability; unresolved provider
outage, retained billable metadata or lost identity leaves cleanup/budget INCOMPLETE.

## Regional pricing, limits and $10 decision

The [machine-readable worksheet](aws-control-canary-costs.json) is the complete
cost-input inventory for this reduced profile. **Known additional-service-charge
subtotal: $0; total/max exposure: unknown; BUDGET NOT PROVEN.** Do not confuse the
subtotal with a complete price quote. No credits, promotional free tier, zero tax,
free operator or maximum failure duration is assumed.

Public references checked 2026-10-20, not account quotes or AWS API calls:

| Cost component | us-east-1 / us-west-2 / global treatment | After 30 minutes / failure |
| --- | --- | --- |
| IAM, STS | [No additional feature charge](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html); same treatment for proposed regional STS probes | Roles have no direct recurring service price; residual privileges and downstream audit charges remain a risk |
| Native CloudFormation | [No additional AWS::* provider charge](https://aws.amazon.com/cloudformation/pricing/); no custom resource/hook introduced | Existing hooks or custom auditing may charge; deleted stack metadata can remain |
| Organizations | [No additional Organizations fee](https://docs.aws.amazon.com/organizations/latest/userguide/pricing.html); existing setup only | Underlying service/support costs do not disappear |
| CloudTrail history | [Default 90-day management history has no charge](https://aws.amazon.com/cloudtrail/pricing/) | Paid duplicate management-event delivery reference $2/100,000, plus S3/KMS/Logs/Lake/queries where configured; quantities and regional destinations unknown |
| Networking and logs | Zero new NAT/VPC endpoint/compute/log resources | API transfer, existing network/security systems, log storage, replicas, retention and taxes require actual regional/account quote |
| KMS / DDB | Zero in both regions | Not priced into this canary. Future KMS reference $1/key-month prorated hourly; pending-deletion storage unbilled unless canceled; minimum wait seven days, possibly another day. RSA signing/API rates and DDB regional units still need quotes |
| Operator, tax, support, failure | Owner jurisdiction, actual time and contracts unknown | Time, support escalation, exchange/payment costs and retained metadata can outlast teardown; no invented cap |

[KMS pricing](https://aws.amazon.com/kms/pricing/) and
[deletion timing](https://docs.aws.amazon.com/kms/latest/developerguide/deleting-keys.html)
explain why PendingDeletion could not count as 30-minute absence if KMS were added.
[DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/) needs a separate
conditional-operation profile; do not reuse unrelated example prices.

Resource type/ARN policies, no-create test roles, fixed role conditions, disabled
templates and runner request/time checks are enforceable within their respective
trust boundaries after real verification. Role counts/deadlines are proposals,
not universal account quotas or hard billing caps. Existing administrators can
change policies. AWS service quotas do not cap all spending. A
[billing alert can arrive after further costs accrue](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
and cannot enforce $10. No budget/alarm is created by this test. Prefer the current
offline botocore/structure checks as the **no-spend alternative** until account
audit/billing/operator information makes the whole exposure supportable.

## Single-use owner approval and review checklist

Fill the separate approval form without credentials. Exact owner-supplied facts:
three existing account IDs/organization, payer and enabled regions; all existing
operator/provisioner/verifier/backup ARNs and availability; SCP/boundary/trust
evidence; inherited audit/hook inventories and regional pricing; tax/currency and
operator costs; original fixed setup/active/teardown/follow-up times; evidence
destination/retention; maximum residual exposure within the **$10 total**, including
cleanup/contingency; authentic independent review and owner approval evidence.

The final single-use envelope binds final engineering SHA, both template hashes,
filled parameters, exact resource names/counts, allowed API cases, account/region
boundaries and the reviewed creation/cleanup protocol. Actual provider-issued IDs
and change-set hashes are appended as receipts under that envelope before action;
they are not fabricated or signed in advance. An external verifier acknowledges
matching processed plans; discrepancies require a new owner decision, not an
automatic replacement attempt. Read-only discovery/change-set creation must be
explicitly included in eventual authorization; present instruction grants none.

Before activation, independent review must confirm: no live network pathway was
enabled by this change; exact trusts and effective grants; no paid KMS/DDB/retention
service implied; account-role ownership; honest budget; no secrets in evidence;
no mutable-tag authority; paginated independent inventory with post-teardown
credentials; change-set ordering/rollback; clock/deadline enforcement; safe error
classification and an actually available cleanup operator. No self-approval here.

## Preservation

Accepted analyzer/scorer, PostgreSQL/control-plane SQL/migration 0004, SDK network
refusal, SQLite custody/watchdog and AWS-10-01 result contract are unchanged.
PRs #9/#10 stay draft/unmerged. CR-04 remains PENDING OWNER DECISION. No owner-key
access, protected source, real repository acquisition, custody, A/B, reveal, scoring,
deployment or Phase 3. Historical 0/84 is unchanged, not a measured 0% accuracy;
EVAL-ENTRY remains UNFROZEN. Historical custodians were not accessed; their original
deadlines remain **2026-11-14 17:43:39 UTC** and **2026-11-16 16:53:29 UTC**.
Host-side cleanup remains a separate owner obligation.
