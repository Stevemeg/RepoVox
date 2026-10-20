# Cloud retention review corrections

Version: `cloud-retention-review-contract-1.2`. Date: 2026-10-20.
Normative **offline design/model** contract, not live cloud authorization. Design
at `95aa6d265038f0b111eec91770690ebd2016a363` was independently accepted for
design-stage engineering only. These corrections require independent re-review.
[Architecture](cloud-retention-design.md) | [ADR-0021](../adr/0021-independent-cloud-retention.md) |
[verification](../delivery/cloud-retention-review-corrections.md).

## Native identities — CR-01

`cloud-retention-model-1.1` supersedes mock protocol 1.0. Fresh disposable SQLite
ledgers use `user_version=110`; older ledgers are rejected, never implicitly
converted. No application migration, historical Store or evaluation schema change.

Authorize `(kind, account, region, parent, key, provider_identifier)` exactly.
The resource commitment also binds tenant, namespace and provisioning receipt.
Duplicates are rejected; identical VersionIds under different keys/buckets or IDs
in different resource kinds remain distinct. Parent kind must match. Principal
ARNs are separate typed values, never aliases interchangeable with raw IDs.

| Field | Representation |
| --- | --- |
| EC2/EBS/snapshot | Exact `i-`, `vol-`, `snap-` ID with 8 or 17 lowercase hex digits, plus account/region |
| General-purpose bucket | Exact lowercase 3..63-character name, dots/hyphens allowed; provider provisioning must also validate reserved-name/IP/partition restrictions |
| Object key | Exact nonempty UTF-8, at most 1,024 bytes; punctuation, control characters and Unicode composition preserved |
| VersionId | Exact opaque UTF-8, at most 1,024 bytes; literal `null` representable for cleanup, refused for new immutable-evidence creation |
| UploadId | Exact nonempty opaque UTF-8 with punctuation; local 16 KiB protocol cap is **not** an asserted AWS limit |

AWS documents [key byte limits and flat key semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html),
[VersionIds and null versions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html)
and [native multipart IDs](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateMultipartUpload.html).
Syntactic validity does not prove AWS accepts a resource. Unsupported profiles fail
closed. No trimming, URL decoding, `+` conversion, case/Unicode normalization,
filesystem resolution or wildcard interpretation. JSON escaping preserves bytes.
Keys are never local paths. Future typed SDK adapters must encode exactly once and
test XML/URL/`encoding-type=url` round trips. Never interpolate native IDs into
shells or wildcard policies. Sensitive names need private registry handling or
opaque-key policy; monitoring receives opaque commitments only.
If a native key cannot be expressed as an exact IAM resource without wildcard
interpretation, a future policy compiler must refuse that profile or prove a
separate exact-operation broker boundary. Model acceptance must never silently
produce a broader deletion grant. No IAM compiler is implemented here.

## Separate authenticated absence verification — CR-02

The immutable root pins different cleanup/verifier principal ARNs and a verifier
public signing key. That service key is separate from the Windows owner key. The
cleaner cannot enroll a verifier, obtain its credentials or sign its observations.

The durable challenge binds nonce, root, fence, exact resource catalog hash and
identities, tenant/namespace/account/region, verifier principal and a 60-second
validity. The independently authenticated read-only provider connection obtains
its own inventory. It must enumerate all approved parents, versions, delete markers,
uploads and compute/storage, including unexpected children regardless of tags.
The cleaner's cached list, success response or credentials are not evidence.

### Enumeration scope and relationship completeness

CR-02 re-review of `43dbcfa178f0b6ffec1164bb5f051f0619d7e363` found that the original
namespace/identity/S3-parent filter could omit EBS descendants. The corrected
fixed read profile is **DEDICATED_ACCOUNT_REGION**: enumerate every present resource
of the six supported kinds in the exact account/region, with no namespace, tenant,
tag, registered-ID or parent filter. No matching lineage is needed for inclusion.
Each returned row must agree with the authenticated endpoint account/region;
wrong-boundary rows and unsupported kinds refuse verification. A legitimate unrelated
resource also prevents an empty-account receipt. It never becomes deletable merely
because it was enumerated. A shared workload account cannot use this empty-account
profile and must remain blocked rather than silently switch to a narrower query.

| Relationship relevant to discovery | Why parent-only matching is insufficient |
| --- | --- |
| Compute to attached EBS volumes | Must inspect every attachment, including unexpected volumes and multiple attachments; detachment can remove the surviving edge |
| EBS volume to snapshots | An unregistered snapshot can refer to a registered volume after that volume is deleted; namespace/tags do not determine inclusion |
| Snapshot to restored volume; volume to copied volume | Derived volumes can be detached and have no compute parent; the mock's single parent field is not a complete provider lineage graph |
| Snapshot copies and backups | Copied snapshots can have an arbitrary source-volume ID; lineage inference alone cannot prove coverage |
| S3 buckets to versions/delete markers/uploads | Include all keys/versions/uploads in every supported bucket in scope, including unregistered destinations; unknown parent names cannot be filtered out |

AWS describes [all volume attachments and snapshot/copy origin fields](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_Volume.html),
[attachment instance identity](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_VolumeAttachment.html)
and [snapshot source-volume limitations for copies](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_Snapshot.html).
These relationships inform discovery and diagnostics, **not deletion authority**.
The offline inventory includes disconnected/transitive descendants conservatively
without pretending its single-parent schema represents all those AWS fields.

Provider-wide enumeration here means account/region-wide for supported kinds, not
every AWS service, other accounts/regions, replicas, AMIs, backups or host exports.
The fixture executes an exhaustive read transaction; a real adapter still needs
independent ownership/region checks, all API pages, permission/error detection,
S3 bucket-region discovery and settled writes. Unknown or inaccessible destinations
cannot be declared absent. Unsupported storage/copy paths remain prohibited until
separately reviewed. Provider-wide enumeration does not itself authorize metadata
access in a shared account or erase original resource-approval requirements.

Parent-scoped enumeration would compute typed transitive descendants from exact
registered roots, including foreign-namespace volumes/snapshots. It cannot by itself
recover detached/copy lineage or unknown exports. That alternative is **not accepted
as an absence proof** by this implementation. It would require a separately approved
scope contract, proven complete relationship evidence and independent tests.

`absence-query-1.2` and `synthetic-cleanup-receipt-1.2` explicitly bind/record the
fixed inventory scope. Signatures and durable nonces bind the full scoped request.
Legacy 1.1 or narrowed queries are refused, never reinterpreted as account-wide.
The immutable root/model 1.1 and SQLite version 110 are unchanged; no old row,
expiry, registration or custody record is rewritten or migrated.

Canonical observations bind the complete challenge, observation time, all kind
coverage, exhaustive-enumeration flag and remaining commitments. Acceptance verifies
the pinned Ed25519 signature, binding, freshness, complete coverage and emptiness.
One transaction rechecks state/fence/catalog and consumes the nonce with a receipt
hash. Forged, reused, expired, wrong-root or partial observations cannot complete.
Concurrent consumption has one winner. Recurring reconciliation remains active.

`ReadOnlyFixtureInventory` uses a separate authenticated SQLite connection opened
`mode=ro`, never shared Python inventory objects. Tests run signing/query in a
separate process and verify read-only enforcement, independent provider presence
despite an empty cleaner inventory, signature and nonce failures. This establishes
offline interface/crypto/transaction behavior, **not AWS IAM or provider truth**.
The provider fixture and credentials are synthetic trusted-service stand-ins.

Live work must authenticate both directions (e.g. restricted cross-account SigV4/
mTLS and service KMS signing), verify actual role sessions and endpoint/account/
region, and test caller denial. [GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)
reports identity; it alone proves neither read-only privileges nor complete inventory.
Verifier needs scoped Describe/List/read-metadata access without payload reads,
deletes, worker privileges or registry mutation. Cleaner must lack verifier signing/
assume-role/impersonation. Trust policies, service deployment, metadata encryption,
key custody and provider pagination tests remain budget-gated AWS work.

## Durable dynamic provider IDs — CR-03

Root-approved bounded creation slots bind operation, kind, exact bucket/key and
request commitment to an already retention-controlled parent. No wildcard slots;
fresh destinations and unique slots required. Dynamic S3 versions/uploads only;
dynamic disks/snapshots need a separately reviewed adapter. No protected bytes
depend on unregistered parents. This is not a distributed transaction.

| State | Transaction and crash rule |
| --- | --- |
| No intent | No provider call allowed |
| PREPARED | Validate active generation 1, tenant, deadline and slot; commit immutable intent before I/O |
| DISPATCHED | Conditional transaction admits exactly one send; uncertain send is never repeated after restart or lost acknowledgment |
| REGISTERED | Append exact returned ID/root-bound request/parent/key atomically with status before acknowledging registration |

Lock order: database transaction; release; provider call; result transaction. No DB
lock spans network I/O. Two dispatchers cannot win one slot. Hash-linked records
and SQL no-update/no-delete triggers detect accidental changes, not administrator
rewrite. Live append heads need separately approved immutable external commitments.

After creation-before-ack crash, first fence and settle provider writes; enumerate
all pages at the exact fresh parent/key. Exactly one unambiguous identity can be
registered for cleanup only. The append grants no execution authority or deadline
extension. Zero/multiple results, wrong scope/receipt, incomplete inventory or
unsettled requests stay INCOMPLETE. Never automatically repeat PutObject, multipart
initiation or analysis. Exact duplicate registration returns its existing commitment;
changed ID/bytes are rejected. No new registration after COMPLETE.

Subprocess tests abruptly exit before dispatch, after dispatch, after durable mock
creation in a separate provider database and after durable registration before ack.
Recovery preserves the original expiry and native ID. Concurrency, substitution,
missing effects and in-flight effects are negative controls, not automatic retries.

AWS has no transaction joining S3 creation and DynamoDB registration; do not assume
that a request hash/client token makes PutObject/multipart initiation idempotent.
Use isolated fresh keys, competing-writer denial and durable request evidence.
[ListObjectVersions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html)
needs key/version pagination and delete-marker handling;
[ListMultipartUploads](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListMultipartUploads.html)
needs key/upload markers for general-purpose buckets. Empty first pages, 403s or
interrupted listings are not absence. A request can finish after guest termination/
credential revocation. If late effects cannot be bounded/settled, COMPLETE is
blocked. Atomic mock quiescence is an explicit assumption, not provider proof.

## Reviewer copies — CR-04

The [owner decision record](cloud-reviewer-copy-decision.json) is explicitly pending.
The [options/runbook](cloud-reviewer-copy-decision.md) defines enforceable choices,
evidence and limitations. No owner selection, signature, processor contract or
destination has been invented. Public-key enrollment does not approve exports.
Synthetic policy eligibility never authorizes a real handoff or proves deletion.
