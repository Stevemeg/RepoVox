# Protected evaluation storage guide

Version `evaluation-storage-1.0`, 2026-10-12. [Existing preparation](evaluation-preparation.md) · [Contamination](evaluation-contamination.md) · [Retention authority](../operations/deployment.md#retention-and-deletion) · [Owner decisions](../delivery/phase2b-decisions.md).

No official custodian has been authorized or provisioned. The Windows screening
temporary directory contains license evidence only and is not protected evaluation
storage. Current tooling rejects native Windows ACL assumptions; an equivalent would
need separate implementation and demonstrated access denial, not a manifest flag.
No paid infrastructure is used or authorized.

Use a local POSIX filesystem outside Git and outside ordinary application volumes,
owned by a dedicated custodian Unix identity, separate from every API/worker/parser/
prompt-development identity. The local application image runs UID 10001; a future
custodian must use a different actual identity and never claim protection through a
declaration that the worker uses a different UID. Check live image/container identity,
mounts, groups, credentials and any privileged/root access. Root/host administrators
remain trusted; DAC does not defend against them. Use 0700 directories and 0600 files,
reject symlinks/special files, and retain immutable versioned bytes in read-only approved
snapshots with checksums. Existing `CustodianStore` writes exclusively and prevents
version-file overwrite; chmod alone is not write-once archival protection.

Suggested private layout:

```text
custodian/
  provenance/<sha256>             # original rights/appointment/review/access evidence
  <family-id>/source/             # pinned original bytes, family holds one split only
  <family-id>/source_manifest.json
  <family-id>/variants/<variant-id>/source/
  preparation.json               # eval-entry-preparation-1.0
  versions/<version>/             # sealed source/gold/manifests and approvals
  withdrawals/                   # minimal suppression and dependent report lineage
```

DEV and TEST source/gold versions need separate authorized paths and access grants;
family split is immutable in each reviewed version. No API/worker mounts, keys or routes
may expose either gold pool. Existing database integration checks no application roles
have evaluation-schema grants. Freeze validation checks actual outside-Git containment,
all descendant permissions/ownership/links, distinct worker UID, original source bytes
and immutable evidence hashes. Private operational access review records actual mounts,
identities, read-only grants, split channels, reviewer access denial outside scope and
backup/restore findings. It must be authenticated by the owner/custodian; arbitrary
hashed text or CLI flags do not prove those operational controls.

Reviewer access is a separately authorized private preparation channel before freeze.
It does not use the application `allowed` runner path: EVAL_TEST is denied there for
annotation/development/prompt tuning. A future isolated final runner receives narrow,
read-only, expiring access only after configuration registration and corpus freeze.
Neither evaluation pool can enter training/calibration. No such runner is implemented
or registered during Phase 2B, and no hidden gold is opened.

The disposable `tools/phase2_storage_probe.py` runs **synthetic bytes only** in a trusted
Linux test image as root, drops to custodian UID 10002, checks 0700/0600, then separately
drops to application-worker UID 10001 and demands an actual OS PermissionError. It
cleans up its temporary files and prints an aggregate. This demonstrates Unix denial
for that disposable directory; it does not establish official storage, live application
mount isolation, reviewer provisioning, backups, hidden-run grants or paid deployment.
Run it with `docker compose -p repovox-test run --rm --no-deps --user 0 --cap-add SETUID --cap-add SETGID --cap-add CHOWN tests python
tools/phase2_storage_probe.py`. Inspect live mounts separately, without printing secrets.

Before official freeze, demonstrate source/gold denied to actual app/worker processes,
controlled reviewer read access, DEV-only development access, TEST development denial,
registered final-only grants, immutable versions and a restore test preserving all
permissions. Backups must use the same rights/access boundary, authorized encryption
and custodian-only recovery credentials. No backup was made here. On withdrawal,
revoke access, invalidate reports, delete live prohibited bytes and apply suppression
lineage on restore; record deletion/backup expiry evidence. Manifest invalidation is
not physical deletion. Owner must approve actual retention and allowed access first.
