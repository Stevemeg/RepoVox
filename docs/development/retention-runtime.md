# Isolated retention runtime and readiness

Status: proposed for independent review, 2026-10-18. This operational tooling is
synthetic-only. It does not authorize or implement a real custodian, acquisition,
prediction generation, reference review, reveal or scoring. See the
[control plane](pilot-control-plane.md), [protected storage](evaluation-storage.md)
and [blind chronology](evaluation-v2-blind-protocol.md).

## Provisioning identity

`tools/phase2_retention_identity.py` validates an independently retained provisioning
plan and creation receipt against actual Docker inspections. Container ID, creation
timestamp, immutable image identity, command/entrypoint, environment, UID/GID,
mounts, volume creation metadata, network and security options must agree. Explicit
namespace, nonce, role, purpose and plan-digest labels corroborate that receipt.
Labels alone cannot discover or authenticate the intended role. The Docker/host
administrator and custody of the receipt remain trusted boundaries.

A standalone retention container is distinguished from a Compose application,
worker or database. Familiar Compose labels inherited from an image are inert;
image-inherited retention identity labels are rejected. Ordinary Compose services
still require their exact project, service and working directory. No global
working-directory bypass exists. Omission of Docker's unset `Config.Cmd` means
`null`; an explicit empty array, different command or different entrypoint cannot
become that unset value through normalization.

Retention requires UID/GID 10002, no supplementary privilege, read-only root,
network none, all capabilities dropped and NoNewPrivs. Its exact registered local
volume has no driver options or subpath. Files are 0600 and custody directories
0700. A privileged initializer applies mode before ownership transfer; subsequent
enumeration runs as the actual custodian. Application/worker UID 10001 must be
denied both enumeration and private-file reads.

## Executable representation

`infrastructure/retention/` contains the canonical launcher, bundle verifier and
watchdog. `tools/phase2_retention_bundle.py` reads bytes and creates a deterministic
tar build context. Executables are UTF-8 without BOM, use LF, end with a newline
and have the expected shebang at byte offset zero. Transfer must preserve exact
SHA-256 values; no implicit PowerShell text conversion is permitted.

The target shell checks syntax. The image verifier checks exact member names,
hashes, regular-file/root ownership, mode 0555, encoding, Python syntax and actual
UID/GID before the launcher execs the watchdog. Image builds use a fully qualified
immutable base repository digest, and retain image IDs and base-layer agreement.

## Startup and health

A running container is not a healthy watchdog. The earlier fixed 0.5-second probe
preceded the observed first heartbeat at approximately 2.715 seconds. The bounded
startup contract allows six seconds: `ceil(2 * 2.715 + 2 * 0.2)`. This is a new
startup allowance, not an extension of evidence freshness or retention expiry.
Missing heartbeat evidence is STARTING/unavailable and never healthy.

`tools/phase2_retention_readiness.py` requires two fresh advancing loop observations
from the same process and boot. Three-second UTC freshness remains unchanged;
monotonic timestamps must also be recent and later than process birth. Process
command, real/effective/saved/filesystem UID/GID, supplementary groups, capabilities,
NoNewPrivs, script hash/mode and container restart count are checked. Malformed,
stale, regressing, replaced, stopped or exited observations fail closed. Observers
receive the remaining startup budget; exceeding it cannot yield readiness.

The isolated Linux operator observes `/proc/<inspected-pid>` through
`tools/phase2_retention_observer.py`, verifies its container cgroup and stable process
birth, then reads the process-root heartbeat and immutable script. This read-only
trusted-host observation avoids charging repeated Python startup to the watchdog's
restricted CPU quota. It adds no container capability or mount. It is not hardware
attestation or protection against a malicious host administrator.

## Synthetic inventory and expiry

The watchdog accepts only `usage: SYNTHETIC_RETENTION_REHEARSAL`, a fresh synthetic
namespace, its committed plan and exact original inventory. It checks UTC deadlines
within 30 days, original bytes, owner/modes, device boundaries and directory-FD path
containment. Unexpected files/directories, links, changed hashes or forged targets
stop processing. A durable exclusive expiry intent precedes deletion; only committed
files are removed, with a separate completion receipt. Restart can finish a retained
intent or confirm completed expiry without renewing the deadline. Concurrent
processors must lose the exclusive lock.

The completed-inventory contract does not support an actively growing real pilot
custodian. No real activation is supplied. A reviewed lifecycle and an independently
verified operational mechanism are required before protected real evidence is
stored. Removing the synthetic-only guard is not an activation procedure.

## Runtime proof

`tests/operational/retention_runtime.py` is an explicitly invoked Linux/Docker matrix,
outside ordinary pytest discovery. The operator must first verify an independent
daemon, disk, network and guest identity, record existing synthetic resources and
pass exact `RV_TEST_DAEMON_ID` and `RV_RETENTION_TEST_ROOT` values. A context name or
project label is insufficient. Real custody, credentials and source are forbidden.

The matrix records original commands, exit codes, stdout/stderr, process identities,
image/volume receipts, before/after hashes and actual filesystem effects. It stops
at the first unexpected result. Expected negative cases must fail for their stated
reason; those rejections are test passes. Prior failed runs remain immutable.
Synthetic volumes may be removed only after checking their full inventory, exact
IDs and exclusive attachments; a prefix alone never authorizes destructive cleanup.

Host tests in `tests/unit/test_retention_*.py` exercise deterministic controls but
cannot substitute for Linux identity, permission, lock, restart or deletion proof.
The [verification and limitations](../delivery/retention-runtime-verification.md)
record actual results separately from official acceptance.

After independently verifying a dedicated disposable guest/daemon, an operator can
prepare a fresh test root as follows. Run only against that guest-local socket as
its trusted operator. Images must already have been acquired and verified; these
commands do not establish endpoint independence. Never point them at shared Docker
Desktop or a real custodian. The example base is the immutable image used by the
recorded rehearsal.

```bash
export RV_TEST_DAEMON_ID=INDEPENDENTLY_VERIFIED_DAEMON_ID
export RV_RETENTION_TEST_ROOT=/opt/repovox-retention-proof-NEW_UNIQUE_ID
export BASE_REF=python@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
python3 - <<'PY'
import json, os, subprocess
from pathlib import Path
from tools.phase2_retention_bundle import create

root = Path(os.environ['RV_RETENTION_TEST_ROOT'])
root.mkdir(mode=0o700, exist_ok=False)
docker = ['docker', '--host', 'unix:///var/run/docker.sock']
info = json.loads(subprocess.check_output(docker + ['info', '--format', '{{json .}}']))
assert info['ID'] == os.environ['RV_TEST_DAEMON_ID']
assert info['DockerRootDir'] == '/var/lib/docker'
assert not subprocess.check_output(docker + ['ps', '-q']).strip()
create('infrastructure/retention', root / 'canonical-transfer.tar')
(root / 'base-image.json').write_bytes(subprocess.check_output(
    docker + ['image', 'inspect', os.environ['BASE_REF']]))
baseline = {name: subprocess.check_output(docker + args).decode().splitlines()
            for name, args in [('containers', ['ps', '-aq']),
                               ('volumes', ['volume', 'ls', '-q'])]}
(root / 'baseline.json').write_text(json.dumps(baseline))
PY
docker --host unix:///var/run/docker.sock build --network none \
  --build-arg BASE_IMAGE="$BASE_REF" -t repovox-synthetic-retention:verified \
  - < "$RV_RETENTION_TEST_ROOT/canonical-transfer.tar"
docker --host unix:///var/run/docker.sock image inspect \
  repovox-synthetic-retention:verified > "$RV_RETENTION_TEST_ROOT/retention-image.json"
PYTHONPATH="$PWD" python3 tests/operational/retention_runtime.py
```

Keep the root, original outputs and any failed fixture intact. This explicit matrix
is never run by normal application/worker services or automatically against an
operator's default Docker context. Normal CI unit discovery does not execute it.

Original custody deadlines remain 2026-11-14 17:43:39 UTC and 2026-11-16 16:53:29
UTC. This code does not activate either watchdog, extend either deadline or remove
the owner's host-copy cleanup and withdrawal obligations. DAC and checksums are not
administrator-proof WORM or authenticated reviewer identity.
