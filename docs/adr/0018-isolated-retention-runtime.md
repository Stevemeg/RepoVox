# ADR-0018: Isolated retention identity and bounded readiness

Status: proposed for independent engineering review. Date: 2026-10-18.

## Context

Standalone retention inherited Compose labels and was misclassified. A Windows
text conversion corrupted executable bytes. Container Running state and a fixed
startup sleep did not prove retention progress. The owner authorized a dedicated
VMware Ubuntu environment, synthetic correction/verification, Phase 2 metadata
preparation and a conditional future real attempt after all required gates.

## Decision

Use a separate guest-local Docker Engine, disk and evidence namespace; never start
shared Docker Desktop or reuse real custody for synthetic proof. Retain original
failures and independently inspect the actual guest/daemon/resources before use.

Provisioning identity comes from a retained plan and creation receipt, corroborated
by exact runtime/image/mount/volume/security checks. Inherited labels cannot select
a role. Ordinary Compose project/service/working-directory checks remain. Docker's
omitted unset command is supported without conflating explicit commands.

Canonical executable files are UTF-8 without BOM, LF-only and byte-committed. Binary
transfer, target syntax, hashes, ownership and modes are verified before execution.
Keep these bytes separate from Windows text conversions and private evidence.

Readiness permits bounded startup but never declares missing evidence healthy.
Within six seconds, require two fresh advancing loops from the same process/boot,
matching source hash, container identity, actual IDs/groups/capabilities, command
and deadline. Existing three-second freshness and UTC expiry are unchanged. Observe
the exact container process through the trusted isolated host's read-only `/proc`
interface to avoid consuming the watchdog's restricted CPU quota with extra Python
processes. No Linux privilege or resource limit is increased.

Retain the existing synthetic-only committed-inventory watchdog. Test actual expiry,
containment, access denial, restart and concurrency with disposable bytes. Do not
remove its real-activation guard or present it as an active-custodian lifecycle.
Protected real evidence requires a separately reviewed operational mechanism first.

## Consequences and limits

No accepted analyzer/scorer, identity mathematics, evaluation schema, control-plane
SQL, grants or historical record changes. The test image additionally copies the
canonical retention files, and pytest imports trusted operational modules from the
repository root. This follow-up image is not an implicit new real-pilot freeze.

Operators/host administrators and receipt custody remain trusted. DAC, timestamps
and checksums are not administrator-proof WORM or reviewer authentication. Existing
custodian deadlines and owner-managed host-copy cleanup remain unchanged. Synthetic
success establishes tested machinery, never source accuracy or official human gold.
Independent review and official EVAL-ENTRY requirements remain separate gates.

See the [operational specification](../development/retention-runtime.md),
[verification](../delivery/retention-runtime-verification.md),
[control-plane ADR](0017-pilot-control-plane-safety.md) and
[protected storage](../development/evaluation-storage.md).
