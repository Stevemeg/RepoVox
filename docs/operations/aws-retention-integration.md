# AWS retention integration contract

Version: `aws-retention-package-1.0`. Date: 2026-10-20. **Offline implementation;
not deployed or independently accepted.** [ADR](../adr/0022-aws-retention-integration.md) |
[test runbook](aws-synthetic-test-runbook.md) | [verification](../delivery/aws-integration-verification.md).

## Architecture and activation boundary

| Boundary | Implementation and authority |
| --- | --- |
| Dedicated workload account | Ubuntu EC2, encrypted root/custody EBS, private VPC, no ingress, no public IPv4, restricted metrics-only guest role |
| Separate security account | Anchored registry, conditional DynamoDB state/intents, opaque Object-Lock archive, separate cleanup/verifier/supervisor Lambdas, service KMS keys, expiry and recurring routes, SQS and SNS |
| Secondary region | Separately scheduled observer and missing-progress alarm; exact cross-account primary read role, no cleanup or protected replica |
| Owner | Supplies real account/region/budget/resource approvals later; owner Ed25519 key stays outside cloud, logs and Git |
| Reviewer | No AWS execution/cleanup credentials. CR-04 remains PENDING; no actual export or owner review operation is granted |

The compiler creates five CloudFormation templates and three concrete synthetic
IAM policy documents under `infra/aws-retention`. Account-reservation template is
optional management-account tooling, never controller authority. All resources have
`Condition: Deploy`; false-by-default `DeploymentAuthorized`, exact account/region
and nonzero approval-hash conditions must all hold. Those conditions are guards,
**not authentication of owner approval**. Schedules remain DISABLED. Lambda code
refuses activation, and SDK before-send handlers refuse all network requests.
No deployment helper or live credential/client factory exists.

The package is suitable for reviewing AWS request construction and state semantics.
It is not a claim that the templates can be activated as a functioning retention
service merely by changing one parameter. A separately authorized/reviewed live
composition must authenticate owner-approved provisioning receipts, read back code
digests and policies, implement settlement proof and activation canaries, bind exact
created IDs, and enable independently verified routes only afterward. Networking
for guest management/health is intentionally closed pending an approved route.
No protected writes are authorized in this package.

## SDK adapters and inventories

| Module | Implemented operations |
| --- | --- |
| `phase2_aws_contract.py` | STS account/session-role checks, region/model validation, before-send refusal, bounded pagination, exact typed identities |
| `phase2_aws_inventory.py` | All account/region instances/disks/owned snapshots/AMIs, Backup vault recovery points, Recycle Bin rules and retained images/snapshots/volumes; all S3 general buckets, versions, markers, uploads and directory-bucket blockers |
| `phase2_aws_cleanup.py` | Exact termination, detached/available volume deletion, snapshot owner check/deletion, exact S3 VersionId/delete-marker deletion, UploadId abort, empty bucket deletion, restartable reconciliation tick |
| `phase2_aws_registry.py` | Atomic root/state creation, readiness/health fence, one-use intents, dispatch, late-result registration, cleanup claims, progress, challenge and nonce consumption |
| `phase2_aws_creation.py` | Checksum-bound single PutObject/native VersionId capture; late identity recovery; no uncertain create replay |
| `phase2_aws_verifier.py` | Independently authenticated inventory, KMS digest signing, pinned public-key verification, coverage/freshness/root/nonce binding |
| `phase2_aws_operations.py` | One-time UTC expiry plus separate recurring schedule requests, fresh loop metrics, sanitized incident delivery |
| `phase2_aws_infrastructure.py` | Reproducible disabled templates, exact destructive-policy compiler and explicit cross-account trust |
| `phase2_aws_budget.py` | $10-ceiling arithmetic, unknown expenses and fail-closed feasibility result |

All SDK clients are injected with explicit synthetic credentials in tests; no
credential chain is consulted. The adapter itself registers a network refusal even
if Stubber is removed. SDK request shape validation and Stubber response validation
are real botocore behavior; provider responses and failures are simulated.

Discovery retains CR-02's **DEDICATED_ACCOUNT_REGION** scope. Never filter by mutable
tags, namespace, tenant, registered identity or parent. Detached/copy lineage is not
needed for inclusion. Unexpected or unrelated resources block empty inventory and
remain undeletable. Other services/accounts/regions, unmanaged exports and copies
are outside this profile, prohibited until separately inventoried. A bucket outside
the approved region fails closed. Directory buckets are detected but unsupported
for protected storage or deletion. AMIs, Backup and Recycle Bin entries/rules block
COMPLETE; there is deliberately no broad deregister/delete-backup/retention-bypass
grant. A snapshot delete success may still leave a retained recovery copy.

Use [complete paginated bucket listing](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html),
[all version/delete-marker pages](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html)
and owned, deprecated/disabled [AMI discovery](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeImages.html).
Repeated/missing pagination markers, response omissions, limits, denied APIs or
unavailable endpoints never become empty proof. S3 opaque IDs and keys are kept
exactly; no URL decoding, Unicode normalization or wildcard matching. SDK XML/URL
round trips still require real disposable API tests.

## IAM and trust

Cleanup grants compile only exact registered ARNs, original region and exact
`s3:VersionId` conditions. Reject IAM wildcard/policy-variable characters rather
than normalizing valid native strings into broader authority. Snapshot ARNs omit
account, so the adapter separately verifies owner before deletion. Multipart IAM
is key-scoped; application checks the exact UploadId. Effective AWS tests must
verify this broker boundary and deny direct unregistered uploads/aborts.

The workload cleanup and verifier roles trust exact security-role ARNs with
ExternalId and PrincipalOrgID conditions. No account-root trust or wildcard role
principal is used for cross-account execution. STS metadata alone cannot prove IAM
least privilege or disambiguate arbitrary role paths; trust and role-session tests
are mandatory. Scheduler trust binds SourceAccount and the exact schedule group,
following [AWS confused-deputy guidance](https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html).

Describe/List inventory APIs require broad read scope; S3 metadata enumeration
uses all owned buckets. These grants are isolated from destructive statements.
Logs permit only streams under `/repovox/`; metrics only the named namespace.
Regular guest workers/API/reviewers/CI have no cleanup, KMS Sign, DynamoDB write,
IAM, Organizations, snapshot, backup or storage-creation grant. The provisioning
identity is an external, separately approved short-lived trust boundary: it must
be revoked and its in-flight creations settled before protected activation.
No tag-based authority is generated.

Security roles have exact table/function/key/topic/queue permissions. KMS keys use
the standard account-root delegation policy for initial key administration; this
is not a grant to a worker. Root/organization administrators remain trusted and
must independently review effective key policies, SCPs/permission boundaries,
grants, resource policies, session policies and emergency access. SCP deployment
and policy-simulator/Access Analyzer/canary proof are **not** established offline.
IAM grants cannot force callers to include a DynamoDB ConditionExpression. The
trusted registry service is the only mutation authority; compromising it is outside
the worker-isolation guarantee. Externally pinned root bytes detect substitution.

## Registry transactions and failure recovery

Root commits owner/tenant/attempt/namespace, account/region, source commitment,
original authorization/retention deadlines, exact resources and creation slots.
Owner provisioning receipt and immutable metadata version pin its hash. Mutable
state never supplies a replacement deadline. Each mutation condition-checks exact
ROOT bytes in its transaction. No TTL or Scan serves as a correctness boundary.

`PENDING -> ACTIVE -> FENCED -> CLEANING -> VERIFYING -> COMPLETE` is the cleanup
protocol. No transition returns execution to ACTIVE. COMPLETE may be revisited by
cleanup/reconciliation with a new fence to detect reappearing bytes; it never grants
execution. Fixed expiry and authorization deadline stay in the original root.
Readiness hash alone is not a live activation proof. Heartbeats must advance a
durable progress counter; writes/dispatch check generation and current health expiry
atomically. Health freshness is capped at the original execution authorization.
Guest/owner/SQL failure cannot disable the external fence or recurring cleanup.

Creation: atomically record approved intent plus outstanding count, then commit
one-use DISPATCHED before sending. API failure or controller crash leaves unresolved
intent; do not automatically create again. Register returned native identity and
decrement outstanding in one transaction, including after fencing for cleanup only.
An exact duplicate after lost acknowledgment returns the same commitment; altered
content is refused. Zero/multiple discovery candidates remain unresolved.

Cleanup claims use conditional generation/lease checks; one worker wins. Each
progress write rechecks owner, generation and current clock. SDK success means
REQUESTED, never absent. Attachment races do not force detach. Errors remain
INCOMPLETE; recurrence is not disabled. An in-flight provider call may finish after
fencing or credential revocation. No AWS API supplies universal immediate write
quiescence, so unproven settlement forbids a verification challenge. This package
has no real settlement issuer; synthetic fixture rows are explicitly labelled.
See [DynamoDB transactions and idempotency limits](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).

Separate KMS RSA-3072 service signatures use `RSASSA_PSS_SHA_256` and DIGEST,
following [KMS Sign](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html).
Verifier holds its own read credentials and signing authority; cleaner does not.
Root, generation, revision, settlement commitment, nonce, tenant/namespace, exact
role/key fingerprint, region/account and 60-second challenge lifetime are bound.
Acceptance checks pinned public DER, signature, complete coverage, observed time,
emptiness and transactionally consumes the original nonce against unchanged state.
No owner private key, signature fixture or approval evidence is reused.

## Monitoring, copies and realistic guarantees

Primary supervisor and independent secondary observer run every minute; two missing
one-minute periods alarm. Fresh progress must be independently confirmed before
write admission. SQS backlog, missing monitor progress, expired authorization and
cleanup failures escalate through SNS HTTPS to an approved incident destination.
Notifications contain fixed reason codes and opaque root commitments, never SDK
errors, source keys or payloads. Primary API/IAM/regional failure can leave resources
OVERDUE; secondary monitoring detects silence but does not pretend primary deletion
occurred. No exact-time physical deletion or 24/7 responder is invented.

Register root/acquisition/database/object-storage/custody disks before any bytes.
Metadata/archive/code/image/log locations must contain only approved opaque or
public engineering bytes. Snapshot/AMI/Backup/replica creation and external exports
are prohibited in the first smoke test. Future enabled S3 payloads require every
version, marker, upload and late result in the registry. External/host copies need
independent enforceable deletion; the EBS cleaner does not cover them. CR-04 remains
[PENDING OWNER DECISION](cloud-reviewer-copy-decision.json), with real Package A
export prohibited until destination, expiry, verification and separate owner grant
are approved. B/reference bytes cannot be exported through that decision.

Provider outages, delayed revocation, IAM regressions, billing suspension, quotas,
deleted registry, unavailable verifier and network partitions fail closed for new
work. Cleanup remains conditional/eventual and INCOMPLETE until independently
verified. Immutable anchors, recurring routes and incident escalation are recovery
tools, not provider availability guarantees. Real custody needs a contracted 24/7
responder; a named daytime synthetic-test operator does not satisfy that gate.

Accepted analyzer/scorer, PostgreSQL/migration 0004, SQLite lifecycle/watchdog and
owner enrollment are unchanged. Historical custodians were not accessed. Old UTC
deadlines remain **2026-11-14 17:43:39** and **2026-11-16 16:53:29**; host-copy cleanup
is still separately owner-managed. Historical 0/84 and official UNFROZEN remain.
