# ADR-0011: Separate acquisition and parser privileges within local workers

Status: Proposed for independent Phase 2 review. Date: 2026-10-12.

[Threat model S-01–S-09](../security/threat-model.md) · [Worker profiles](../operations/deployment.md#worker-profiles-and-resource-limits) · [Tests](../development/testing.md)

Keep one orchestration service. Its trusted acquisition transport constructs only
GitHub API/codeload HTTPS requests, validates every DNS answer at connection, connects
to a numeric address and validates TLS for the original hostname. It ignores proxy
environment and rejects every redirect. This is stricter than allowing two validated
redirects. An aggregate watchdog closes overdue sockets; a bounded DNS resolver has
four slots and a three-second wait. An upstream 404 cannot reliably distinguish a
missing repository from a private one, because GitHub intentionally hides private
existence ([GitHub troubleshooting](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api)).
Metadata explicitly reporting private visibility and HTTP 410 have distinct codes.

Parsing/verification runs in a fresh trusted Python subprocess with scrubbed
environment, no DB/storage/provider credentials, Linux Landlock read access only to
assigned source/request and trusted runtime libraries, and seccomp denial of sockets,
new execution/process creation, ptrace, mount, namespaces and io_uring. Native parser
watchdogs, CPU/address-space/file/descriptor limits and parent stage/lease monitoring
bound work. Unsupported kernels/root execution fail closed; Windows host execution
cannot claim containment.

Worker containers run as UID 10001, read-only base, dropped capabilities,
no-new-privileges, 1 CPU, 2 GiB memory, 128 PIDs and a 2 GiB noexec/nosuid/nodev tmpfs.
No Docker socket or host networking/mount is provided. Acquisition has transport
access to GitHub plus trusted DB/queue/storage; parser sockets are denied entirely.
This is process-level privilege separation, not a separate parser microservice.
Finite local probes do not establish production containment or eliminate native
parser/kernel vulnerabilities. Cloud network/IAM and image promotion remain later gates.

SeaweedFS local capacity is increased from two to sixteen 100 MiB volumes. The initial
default collection consumed both old slots, preventing private-bucket allocation in
real integration tests. No persistent development volume is reset by the change.
This local capacity is not a production storage sizing or durability claim.
