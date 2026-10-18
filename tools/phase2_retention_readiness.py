"""Bounded readiness for the synthetic-only retention contract.

The six-second startup budget is ceil(2 * 2.715s measured cold start + 2 * 0.2s
cadence). It does not extend the UTC retention deadline or three-second freshness.
The observer must impose its supplied remaining timeout on all external operations.
"""

import math
import time
from datetime import UTC, datetime

from tools.phase2_retention_identity import (
    readiness,
    require,
    validate_container,
    validate_heartbeat,
)

STARTUP_SECONDS = 6.0
FRESH_SECONDS = 3.0
WATCHDOG = ["/usr/local/bin/python", "-I", "/opt/rv-retention/watchdog.py"]
STARTING = ["/bin/sh", "/opt/rv-retention/launcher.sh"]


def process_identity(process):
    require(
        process["uid"] == [10002] * 4
        and process["gid"] == [10002] * 4
        and set(process["groups"]) <= {10002},
        "process_identity",
    )
    require(
        process["caps"]
        and set(process["caps"]) == {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
        and all(int(v, 16) == 0 for v in process["caps"].values())
        and process["no_new_privs"] == 1,
        "process_capabilities",
    )
    require(process["state"] not in {"T", "t", "Z", "X"}, "process_identity_or_stall")


def wait_ready(plan, receipt, observe, *, monotonic=time.monotonic, sleep=time.sleep, utc=None):
    """Return only after two real, fresh loop observations from one process.

    Missing evidence is STARTING, never healthy. Malformed or mismatched evidence
    fails immediately. Exit/restart/identity changes also fail immediately. A repeated
    heartbeat may await the next cadence, but never beyond its freshness bound.
    """
    utc = utc or (lambda: datetime.now(UTC))
    started = monotonic()
    first = None
    birth = None
    restart_count = None
    observations = 0
    while True:
        remaining = STARTUP_SECONDS - (monotonic() - started)
        require(remaining > 0, "startup_timeout")
        observed = observe(remaining)
        observations += 1
        require(monotonic() - started <= STARTUP_SECONDS, "startup_timeout")
        container = observed["container"]
        validate_container(plan, receipt, container, observed["image"], observed["volumes"])
        state = container["State"]
        require(
            state["Running"]
            and not state["Restarting"]
            and not state["Paused"]
            and not state["OOMKilled"]
            and state["Pid"] > 0,
            "watchdog_unavailable",
        )
        if restart_count is None:
            restart_count = container["RestartCount"]
        require(container["RestartCount"] == restart_count, "watchdog_restarted")
        process = observed["process"]
        process_identity(process)
        require(process["cmdline"] in [STARTING, WATCHDOG], "unexpected_process")
        require(observed["script_sha256"] == plan["script_sha256"], "script_hash")
        require(observed["script_owner"] == [0, 0, 0o555], "script_permissions")
        if birth is None:
            birth = process["start_monotonic_ns"]
        require(process["start_monotonic_ns"] == birth, "watchdog_process_changed")
        wall = utc()
        deadline = datetime.fromisoformat(plan["deadline"])
        require(deadline.utcoffset().total_seconds() == 0 and wall < deadline, "heartbeat_deadline")
        heartbeat = observed["heartbeat"]
        if heartbeat is None:
            require(first is None, "heartbeat_disappeared")
        else:
            require(process["cmdline"] == WATCHDOG, "unexpected_process")
            validate_heartbeat(plan, heartbeat, wall)
            age = (observed["monotonic_ns"] - heartbeat["monotonic_ns"]) / 1e9
            require(
                math.isfinite(age)
                and 0 <= age <= FRESH_SECONDS
                and heartbeat["monotonic_ns"] >= birth,
                "heartbeat_monotonic_binding",
            )
            if first is None:
                first = heartbeat
            else:
                require(heartbeat["boot"] == first["boot"], "heartbeat_boot_changed")
                require(
                    heartbeat["sequence"] >= first["sequence"]
                    and heartbeat["monotonic_ns"] >= first["monotonic_ns"],
                    "heartbeat_regressed",
                )
                if heartbeat["sequence"] > first["sequence"]:
                    result = readiness(
                        plan,
                        receipt,
                        container,
                        observed["image"],
                        observed["volumes"],
                        first,
                        heartbeat,
                        process,
                        now=wall,
                    )
                    return result | {
                        "startup_elapsed_seconds": monotonic() - started,
                        "observations": observations,
                        "startup_budget_seconds": STARTUP_SECONDS,
                    }
                require(heartbeat == first, "heartbeat_repeated_sequence_changed")
        sleep(min(0.2, max(0, STARTUP_SECONDS - (monotonic() - started))))
