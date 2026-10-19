"""Guest-local restricted lifecycle watchdog. No Docker socket, broker or DB credential."""

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tools.phase2_custodian_lifecycle import Lifecycle, canonical, digest, identity, require, strict


def validate_progress(first, second, plan, process, source_sha256, now=None):
    """Trusted observer supplies actual /proc evidence, never heartbeat self-report."""
    now = now or datetime.now(UTC)
    for heartbeat in [first, second]:
        require(heartbeat is not None, "heartbeat_absent")
        require(
            heartbeat["version"] == "custodian-lifecycle-1.0"
            and heartbeat["namespace"] == plan["namespace"]
            and heartbeat["plan_sha256"] == digest(canonical(plan)),
            "heartbeat_binding",
        )
        require(
            heartbeat["state"] in {"CREATED", "ACTIVE", "SEALED"}
            and heartbeat["inventory_checked"] is True,
            "retention_unavailable",
        )
        require(
            heartbeat["expires_at"] == plan["expires_at"]
            and now.timestamp() < datetime.fromisoformat(plan["expires_at"]).timestamp(),
            "retention_deadline",
        )
        checked = datetime.fromisoformat(heartbeat["checked_at"])
        require(
            checked.utcoffset().total_seconds() == 0 and 0 <= (now - checked).total_seconds() <= 3,
            "heartbeat_stale",
        )
        require(heartbeat["script_sha256"] == source_sha256, "watchdog_source")
    require(
        first["boot"] == second["boot"]
        and first["sequence"] < second["sequence"]
        and first["monotonic_ns"] < second["monotonic_ns"],
        "watchdog_stalled",
    )
    require(
        process["uid"] == process["gid"] == [10002] * 4 and set(process["groups"]) <= {10002},
        "watchdog_identity",
    )
    require(
        set(process["caps"]) == {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
        and all(int(v, 16) == 0 for v in process["caps"].values())
        and process["no_new_privs"] == 1,
        "watchdog_privileges",
    )
    require(
        process["state"] not in {"T", "t", "X", "Z"}
        and process["source_sha256"] == source_sha256
        and process["command_matches"] is True,
        "watchdog_process",
    )
    require(
        process["birth_ns"] <= first["monotonic_ns"]
        and 0 <= time.monotonic_ns() - second["monotonic_ns"] <= 3_000_000_000,
        "watchdog_process_birth",
    )
    return {
        "namespace": plan["namespace"],
        "plan_sha256": digest(canonical(plan)),
        "observed_at": now.isoformat(),
        "progress": [first["sequence"], second["sequence"]],
        "runtime_verified": True,
    }


def run(config_path, status_dir):
    identity()
    raw = Path(config_path).read_bytes()
    require(
        digest(raw) == os.environ.get("RV_CUSTODIAN_CONFIG_SHA256"), "watchdog_config_commitment"
    )
    config = strict(raw)
    require(set(config) == {"root", "plan", "receipt"}, "watchdog_config_fields")
    lifecycle = Lifecycle(config["root"], config["plan"], config["receipt"])
    with lifecycle.watchdog_lock():
        loop(lifecycle, status_dir)


def loop(lifecycle, status_dir):
    boot, sequence = uuid.uuid4().hex, 0
    while True:
        try:
            result = lifecycle.tick()
        except BlockingIOError:
            # A busy writer is not a successful inventory check or healthy heartbeat.
            time.sleep(0.1)
            continue
        sequence += 1
        result.update(
            boot=boot,
            sequence=sequence,
            checked_at=datetime.now(UTC).isoformat(),
            monotonic_ns=time.monotonic_ns(),
            script_sha256=digest(Path(__file__).read_bytes()),
        )
        target = Path(status_dir) / "heartbeat.json"
        temp = target.with_suffix(".tmp")
        fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(result))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        print(json.dumps(result), flush=True)
        if result["state"] == "EXPIRED":
            return
        time.sleep(0.2)


if __name__ == "__main__":
    run(*sys.argv[1:])
