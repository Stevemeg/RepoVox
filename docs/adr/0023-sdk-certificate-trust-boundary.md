# ADR-0023: Explicit, versioned SDK certificate trust

Status: proposed; independent security review required. Date: 2026-10-23.

The owner authorized isolated botocore hardening from exact PR #13
`caf540fb582a0609acb0e62728467e6a58ce9f50`. This decision does not authorize AWS,
deployment, a pilot, new evidence, credential discovery or changes to frozen
analysis, SQL, custody or evaluation contracts.

## Decision

Use the officially published botocore 1.43.118 removal of the AAA root. Preserve
compatible boto3/s3transfer versions and all unrelated lock records. Never edit an
installed third-party bundle. Pin and inspect both the upstream fallback and the
approved certifi distribution. A newer version number is not sufficient evidence.

Route RepoVox transport construction through `repovox.sdk_trust.create_client`.
Require exact versions, distribution containment, regular single-link files,
original CA SHA-256 commitments and parsed DER root checks before creating the SDK
transport. Require explicit identity, endpoint and region. Reject verify=False,
custom paths, ambient CA/profile/config/endpoint/proxy overrides and proxy-specific
CA/client-certificate settings. Shared default AWS files are disabled via public
SDK session configuration to the OS null device; no owner credential files are read.

The factory passes the approved path explicitly, disables ambient proxy lookup,
and revalidates trust before each real send. The offline SDK adapter additionally
validates injected clients before its existing independent network-refusal hook.
This adds no AWS activation route and does not change resource authorization,
fencing, cleanup mathematics, leases or the established refusal error contract.

Run cfn-lint as trusted static tooling with the same installed-bundle inspection
and an irreversible Python socket audit-hook refusal. It cannot use arbitrary
third-party clients to make Python SDK network connections. This is not an OS
sandbox for malicious native code or a general-purpose cfn-lint deployment route.

## Consequences and limits

Controlled uv installs use copy mode: public CA material must not share writable
cache inodes. Missing certifi fails despite the now-clean fallback. Changed or
future SDK/CA versions require explicit review, not a silently accepted update.
Regular application storage keeps its accepted local HTTP behavior; TLS policy
does not pretend local HTTP provides TLS. Type stubs are imported only for typing,
allowing the actual runtime-only storage constructor to work without dev packages.

No Python factory defends against arbitrary hostile code running in the same
process, privileged filesystem modification, or replacement of the interpreter.
Read-only images, existing privilege controls and trusted dependency installation
remain part of the boundary. Revalidation narrows mutable-file exposure but is not
a hostile-host atomic filesystem-to-OpenSSL guarantee. The owner Windows store,
unrelated/old environments, action-internal and browser stores remain separate.
See [complete evidence and reproduction](../security/botocore-trust-hardening.md).
